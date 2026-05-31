import {
  Button,
  Card,
  Divider,
  Spinner,
  Text,
  tokens,
} from "@fluentui/react-components";
import { WeatherMoonRegular, WeatherSunnyRegular } from "@fluentui/react-icons";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useTheme } from "../theme/ThemeContext";

interface AuthConfig {
  configured: boolean;
  dev_mode: boolean;
  issuer: string;
}

export function Login() {
  const { user, loading, login, devLogin } = useAuth();
  const { mode, toggle } = useTheme();
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
    <div
      style={{
        height: "100vh",
        display: "grid",
        placeItems: "center",
        background: tokens.colorNeutralBackground2,
        position: "relative",
      }}
    >
      <Button
        appearance="subtle"
        aria-label="Toggle theme"
        icon={
          mode === "dark" ? <WeatherSunnyRegular /> : <WeatherMoonRegular />
        }
        onClick={toggle}
        style={{ position: "absolute", top: 16, right: 16 }}
      />
      <Card style={{ width: 380, padding: 32, textAlign: "center" }}>
        <Text size={700} weight="bold" block style={{ marginBottom: 6 }}>
          ⚡ VoidSwitch
        </Text>
        <Text
          size={300}
          block
          style={{ color: tokens.colorNeutralForeground3, marginBottom: 28 }}
        >
          Multi-provider LLM API gateway
        </Text>
        {loading ? (
          <Spinner label="Checking session…" />
        ) : (
          <>
            <Button
              appearance="primary"
              size="large"
              onClick={login}
              disabled={busy}
              style={{ width: "100%" }}
            >
              Sign in with Prism
            </Button>
            {config?.dev_mode ? (
              <>
                <Divider style={{ margin: "20px 0" }}>dev mode</Divider>
                <Button
                  appearance="outline"
                  size="large"
                  onClick={handleDev}
                  disabled={busy}
                  style={{ width: "100%" }}
                >
                  Developer sign-in (no OAuth)
                </Button>
                <Text
                  size={200}
                  block
                  style={{
                    color: tokens.colorNeutralForeground3,
                    marginTop: 10,
                  }}
                >
                  Bypasses Prism — local development only.
                </Text>
              </>
            ) : null}
            {error ? (
              <Text
                size={200}
                block
                style={{
                  color: tokens.colorPaletteRedForeground1,
                  marginTop: 12,
                }}
              >
                {error}
              </Text>
            ) : null}
          </>
        )}
      </Card>
    </div>
  );
}
