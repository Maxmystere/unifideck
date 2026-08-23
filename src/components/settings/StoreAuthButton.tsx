/**
 * StoreAuthButton — compact connect / disconnect button used in
 * `StoreConnections` per-store rows.
 *
 * Two visual states: disconnected (standard button with the
 * "authenticate" label) and connected (red background with a
 * logout icon; hover/focus inverts to white-on-red). Returns null
 * for transient states (`checking` / `error`) so the row only shows
 * the action once the auth status is meaningful.
 *
 * Ported from `staging:src/components/settings/StoreAuthButton.tsx`.
 */
import { FC } from "react";
import { DialogButton } from "@decky/ui";
import { useTranslation } from "react-i18next";
import { FiLogOut } from "react-icons/fi";
import type { StoreId } from "../../types/api";

interface Props {
  store: StoreId;
  status: string;
  onConnect: (store: StoreId) => void;
  onDisconnect: (store: StoreId) => void;
  busy?: boolean;
}

export const StoreAuthButton: FC<Props> = ({
  store,
  status,
  onConnect,
  onDisconnect,
  busy,
}) => {
  const { t } = useTranslation();
  if (status === "checking" || status === "error") return null;
  const isConnected = status === "connected";
  // Styles live in `storeConnections.css.ts` and are rendered once by
  // `StoreConnections`. They used to be an inline `<style>` here, which
  // meant the same block was parsed once per store row.
  return (
    <>
      <DialogButton
        disabled={busy}
        className={`unifideck-store-auth-button ${
          isConnected ? "connected" : "disconnected"
        }`}
        onClick={() => (isConnected ? onDisconnect(store) : onConnect(store))}
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "4px 10px",
          fontSize: 10,
          height: 28,
          width: "fit-content",
          minWidth: "unset",
        }}
      >
        {isConnected ? (
          <FiLogOut size={12} />
        ) : (
          t("storeConnections.authenticate")
        )}
      </DialogButton>
    </>
  );
};
