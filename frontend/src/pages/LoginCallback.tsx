import { Spinner, Text, tokens } from "@fluentui/react-components";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { setToken } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { AuthShell } from "../components/AuthShell";
import { ErrorText } from "../components/ui";
import type { Translations } from "../i18n/locales/en";

type TK = keyof Translations;

export function LoginCallback() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { reload } = useAuth();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const hash = new URLSearchParams(location.hash.replace(/^#/, ""));
    const token = hash.get("access_token");
    const err = hash.get("error");
    if (err) {
      setError(err);
      return;
    }
    if (token) {
      setToken(token);
      void reload().then(() => navigate("/", { replace: true }));
    } else {
      setError("missing_token");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <AuthShell maxWidth={360}>
      {error ? (
        <div style={{ textAlign: "center" }}>
          <Text
            size={500}
            weight="semibold"
            block
            style={{ marginBottom: 8 }}
          >
            {error === "access_denied"
              ? t("login.accessDeniedTitle" as TK)
              : t("login.signInFailed" as TK)}
          </Text>
          <ErrorText
            error={error === "access_denied" ? t("login.accessDenied" as TK) : error}
          />
          <Text
            as="span"
            onClick={() => navigate("/login", { replace: true })}
            style={{
              cursor: "pointer",
              marginTop: 16,
              display: "block",
              color: tokens.colorBrandForeground1,
            }}
          >
            {t("login.tryAgain" as TK)}
          </Text>
        </div>
      ) : (
        <div style={{ display: "grid", placeItems: "center" }}>
          <Spinner label={t("login.completing" as TK)} />
        </div>
      )}
    </AuthShell>
  );
}
