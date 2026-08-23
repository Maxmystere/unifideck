/**
 * StorefrontLauncher — open a store's shop with the session the user
 * already has, and put the plugin's tokens back in step afterwards.
 *
 * Deliberately NOT part of `AuthDispatcher`. Opening a shop is not a
 * sign-in: it must not take the auth mutex, must not raise the
 * "Signing in…" toast, and must not resolve on `STORE_AUTH_*`. Sharing
 * that machinery would mean a shop that failed to open could flip the
 * store's row to `error`, where the settings UI renders no button at
 * all — stranding the user with no way to sign in or out over a
 * shopping trip.
 *
 * Two shapes, because the six stores authenticate two ways:
 *
 *   Epic / GOG / Amazon / Microsoft — sign in through the bundled Edge
 *     against a persistent profile. The shop opens in that same
 *     profile, so the live web session carries over. Their cookies are
 *     cleared only immediately BEFORE a real sign-in, which is exactly
 *     why this path must never call `store_auth(store, "start")`.
 *
 *   Ubisoft / Battle.net — sign in inside a Wine prefix, in the vendor
 *     client. They have no browser session at all; their signed-in shop
 *     is the client's own Store/Shop tab, reached by opening the client
 *     in the auth prefix. Here `store_auth(store, "start")` IS called,
 *     and is load-bearing: it arms the session monitor that captures a
 *     rotated token. Neither wrapper store's `start_auth` touches
 *     cookies or deletes anything.
 */
import { call } from "@decky/api";
import { EventBusClient } from "../../api/event-bus-client";
import { rpcRoutes } from "../../api/rpc-routes";
import { unwrapRpcEnvelope } from "../../api/useRPC";
import { prepareForSync } from "../../lib/steam-bridge/prepare-sync";
import { watchAppStopped } from "../../lib/steam-bridge/shortcut-types";
import { authStore } from "../../stores/auth-store";
import { Events } from "../../types/events";
import {
  launchAmazonStorefrontViaShortcut,
  launchEpicStorefrontViaShortcut,
  launchGogStorefrontViaShortcut,
  launchMicrosoftStorefrontViaShortcut,
} from "../../utils/authShortcutLaunch";
import { launchWrapperAuthViaShortcut } from "../../lib/steam-bridge/wrapper-shortcut-launch";
import { BATTLENET_SHORTCUT_CONFIG } from "../../utils/battlenetShortcutLaunch";
import { UBISOFT_SHORTCUT_CONFIG } from "../../utils/ubisoftShortcutLaunch";
import { storeReportsConnected } from "../auth/store-status";
import type { ShortcutLaunchResult } from "../../lib/steam-bridge/shortcut-types";
import type { StoreId } from "../../types/api";

/**
 * How long to wait after the shop closes for the token reconcile to
 * land before syncing anyway.
 *
 * With the web session live the provider redirects through without a
 * login form, so this normally resolves in a second or two. The wait
 * matters because the sync must use the tokens for whatever account the
 * user ended on — syncing first would pull the OLD account's library.
 */
const RECONCILE_WAIT_MS = 45 * 1000;

/**
 * Env token telling the launcher a reconcile was armed for THIS run.
 *
 * The launcher must not simply look for the store's auth-URL file: that
 * file survives from the last real sign-in, so an un-armed shop close
 * would open a stale OAuth URL and pop a login window nobody asked for,
 * with nothing waiting to capture the code.
 */
const RECONCILE_ENV = "UNIFIDECK_STOREFRONT_RECONCILE";

/** Stores whose shop is a web page in the shared Edge profile. */
const BROWSER_STOREFRONTS: Partial<
  Record<
    StoreId,
    (env: Record<string, string>) => Promise<ShortcutLaunchResult>
  >
> = {
  epic: launchEpicStorefrontViaShortcut,
  gog: launchGogStorefrontViaShortcut,
  amazon: launchAmazonStorefrontViaShortcut,
  microsoft: launchMicrosoftStorefrontViaShortcut,
};

/** Stores whose shop is a tab inside their own Windows client. */
const CLIENT_STOREFRONTS: Partial<
  Record<StoreId, () => Promise<ShortcutLaunchResult>>
> = {
  ubisoft: () =>
    launchWrapperAuthViaShortcut(UBISOFT_SHORTCUT_CONFIG, "storefront"),
  battlenet: () =>
    launchWrapperAuthViaShortcut(BATTLENET_SHORTCUT_CONFIG, "storefront"),
};

/** Whether this store has a shop the cart can open at all. */
export function hasStorefront(store: StoreId): boolean {
  return store in BROWSER_STOREFRONTS || store in CLIENT_STOREFRONTS;
}

/** Resolve one bus event for `store`, or time out. Never rejects. */
function waitForReconcile(store: StoreId): Promise<void> {
  return new Promise<void>((resolve) => {
    const unsubs: Array<() => void> = [];
    let settled = false;
    const finish = (): void => {
      if (settled) return;
      settled = true;
      for (const u of unsubs) u();
      resolve();
    };
    const onEvent = (payload: Record<string, unknown>): void => {
      if (payload.store === store) finish();
    };
    unsubs.push(
      EventBusClient.subscribe(Events.STORE_SESSION_RECONCILED, onEvent),
      EventBusClient.subscribe(Events.STORE_SESSION_RECONCILE_FAILED, onEvent),
    );
    const timer = window.setTimeout(finish, RECONCILE_WAIT_MS);
    unsubs.push(() => window.clearTimeout(timer));
  });
}

/**
 * Arm the token reconcile that runs once the shop window closes.
 *
 * Returns whether it actually took — the launcher only redeems the
 * armed URL when told so explicitly. Best-effort otherwise: a store
 * that cannot reconcile must still get its shop opened.
 */
async function armReconcile(store: StoreId): Promise<boolean> {
  try {
    const raw = await call<[StoreId], unknown>(
      rpcRoutes.reconcileStoreSession,
      store,
    );
    const data = unwrapRpcEnvelope<{ success?: boolean }>(raw, {
      route: rpcRoutes.reconcileStoreSession,
      throwing: false,
    });
    return data?.success === true;
  } catch (e) {
    console.warn(`[StorefrontLauncher:${store}] reconcile arm failed:`, e);
    return false;
  }
}

/**
 * Bring the plugin back in step with whatever happened in the shop.
 *
 * Order matters. Refresh auth status FIRST, so a token that died in
 * there (the user signed out, or switched to an account we could not
 * re-exchange for) flips the row to disconnected. Only then sync — and
 * only if the store still reports connected, because `request_auth_sync`
 * triggers the post-sync reconcile sweep, which REMOVES a logged-out
 * store's shortcuts. Syncing a store we just lost would delete the
 * user's library tiles for it.
 */
async function settleAfterClose(
  store: StoreId,
  reconciling: boolean,
): Promise<void> {
  // Only wait when there is something to wait for. Waiting on a
  // reconcile that was never armed would just burn the full timeout
  // before every post-shop sync.
  if (reconciling) await waitForReconcile(store);
  await authStore.refetch();
  if (!(await storeReportsConnected(store))) {
    console.log(
      `[StorefrontLauncher:${store}] not connected after shop — skipping sync`,
    );
    return;
  }
  try {
    await prepareForSync();
    await call<[StoreId], unknown>(rpcRoutes.requestAuthSync, store);
  } catch (e) {
    console.error(`[StorefrontLauncher:${store}] post-shop sync failed:`, e);
  }
}

/**
 * Open `store`'s shop, then settle auth + library state once it closes.
 *
 * Resolves as soon as the window has been asked to open — the settle
 * work continues in the background, keyed off Steam's app-stopped
 * notification, so the QAM stays responsive while the user shops.
 */
export async function openStorefront(
  store: StoreId,
): Promise<ShortcutLaunchResult> {
  const browserLaunch = BROWSER_STOREFRONTS[store];
  const clientLaunch = CLIENT_STOREFRONTS[store];
  if (!browserLaunch && !clientLaunch) {
    return { success: false, error: `No storefront for ${store}` };
  }
  EventBusClient.bumpToFast();
  let result: ShortcutLaunchResult;
  let reconciling = false;
  if (browserLaunch) {
    reconciling = await armReconcile(store);
    result = await browserLaunch(reconciling ? { [RECONCILE_ENV]: "1" } : {});
  } else {
    // The wrapper stores' own arming step. Unlike the browser stores'
    // reconcile, this is the ordinary sign-in kick — it starts the
    // session monitor, which is what notices a token the vendor client
    // rotates while the user is in its shop.
    await call<[StoreId, string], unknown>(
      rpcRoutes.storeAuth,
      store,
      "start",
    ).catch((e) => {
      console.warn(`[StorefrontLauncher:${store}] store_auth kick failed:`, e);
    });
    result = await clientLaunch!();
  }
  const appId = result.app_id;
  if (result.success && appId) {
    watchAppStopped(appId, () => {
      void settleAfterClose(store, reconciling);
    });
  }
  return result;
}
