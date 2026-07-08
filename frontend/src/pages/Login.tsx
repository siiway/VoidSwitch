import {
  Button,
  Divider,
  Field,
  Input,
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
import type { AuthConfig } from "../api/types";
import type { Translations } from "../i18n/locales/en";

type TK = keyof Translations;

export function Login() {
  const { t } = useTranslation();
  const { user, loading, login, tokenLogin, devLogin } = useAuth();
  const { scheme, toggle } = useTheme();
  const navigate = useNavigate();
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tokenOpen, setTokenOpen] = useState(false);
  const [loginToken, setLoginToken] = useState("");

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

  async function handleTokenLogin() {
    setBusy(true);
    setError(null);
    try {
      await tokenLogin(loginToken);
      navigate("/", { replace: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const version = config
    ? `VoidSwitch v${config.version}${config.commit ? ` (${config.commit})` : ""}`
    : "VoidSwitch";

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
          {tokenOpen ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <Divider>{t("login.tokenDivider" as TK)}</Divider>
              <Field label={t("login.tokenLabel" as TK)}>
                <Input
                  type="password"
                  value={loginToken}
                  disabled={busy}
                  onChange={(_, d) => setLoginToken(d.value)}
                />
              </Field>
              <Button
                appearance="outline"
                disabled={busy || !loginToken.trim()}
                onClick={handleTokenLogin}
              >
                {t("login.tokenSubmit" as TK)}
              </Button>
            </div>
          ) : null}
          {error ? <ErrorText error={error} /> : null}
        </>
      )}
      <div style={{ textAlign: "center", display: "grid", gap: 4 }}>
        {!tokenOpen ? (
          <Button
            appearance="transparent"
            size="small"
            onClick={() => setTokenOpen(true)}
            style={{ color: tokens.colorNeutralForeground3 }}
          >
            {t("login.useToken" as TK)}
          </Button>
        ) : null}
        <Text size={100} style={{ color: tokens.colorNeutralForeground3 }}>
          {version}
        </Text>
      </div>
    </AuthShell>
  );
}
