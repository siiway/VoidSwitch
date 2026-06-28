import {
  Button,
  Divider,
  Spinner,
  Text,
  Tooltip,
  tokens,
} from "@fluentui/react-components";
import { WeatherMoonRegular, WeatherSunnyRegular } from "@fluentui/react-icons";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useTheme } from "../theme/ThemeContext";
import { AuthShell } from "../components/AuthShell";
import { ErrorText } from "../components/ui";
import type { Translations } from "../i18n/locales/en";

type TK = keyof Translations;

interface AuthConfig {
  configured: boolean;
  dev_mode: boolean;
  issuer: string;
}

export function Login() {
  const { t } = useTranslation();
  const { user, loading, login, devLogin } = useAuth();
  const { scheme, toggle } = useTheme();
  const navigate = useNavigate();
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && user) navigate("/", { replace: true });
  }, [loading, user, navigate]);

  useEffect(() => {
    api
      .get<AuthConfig>("/api/auth/config")
      .then(setConfig)
      .catch(() => setConfig(null));
  }, []);

  async function handleDev() {
    setBusy(true);
    setError(null);
    try {
      await devLogin();
      navigate("/", { replace: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell hideBrand>
      <Tooltip content={t("login.toggleTheme" as TK)} relationship="label">
        <Button
          appearance="subtle"
          aria-label={t("login.toggleTheme" as TK)}
          icon={
            scheme === "dark" ? <WeatherSunnyRegular /> : <WeatherMoonRegular />
          }
          onClick={toggle}
          style={{ position: "absolute", top: 16, right: 16, zIndex: 2 }}
        />
      </Tooltip>

      <div style={{ textAlign: "center" }}>
        <Text size={700} weight="bold" block style={{ marginBottom: 6 }}>
          {t("login.brand" as TK)}
        </Text>
        <Text
          size={300}
          block
          style={{ color: tokens.colorNeutralForeground3 }}
        >
          {t("login.tagline" as TK)}
        </Text>
      </div>

      {loading ? (
        <div style={{ display: "grid", placeItems: "center" }}>
          <Spinner label={t("login.checking" as TK)} />
        </div>
      ) : (
        <>
          <Button
            appearance="primary"
            size="large"
            onClick={login}
            disabled={busy}
            style={{ width: "100%" }}
          >
            {t("login.signIn" as TK)}
          </Button>
          {config?.dev_mode ? (
            <>
              <Divider>{t("login.devMode" as TK)}</Divider>
              <Button
                appearance="outline"
                size="large"
                onClick={handleDev}
                disabled={busy}
                style={{ width: "100%" }}
              >
                {t("login.devSignIn" as TK)}
              </Button>
              <Text
                size={200}
                block
                style={{
                  color: tokens.colorNeutralForeground3,
                  textAlign: "center",
                }}
              >
                {t("login.devHint" as TK)}
              </Text>
            </>
          ) : null}
          {error ? <ErrorText error={error} /> : null}
        </>
      )}
    </AuthShell>
  );
}
