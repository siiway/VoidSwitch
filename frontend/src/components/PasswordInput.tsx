// PasswordInput — a drop-in replacement for <Input type="password"> with an
// accessible show/hide eye toggle. The toggle lives in `contentAfter` as a
// transparent icon Button wrapped in a Tooltip, and is kept out of the tab order
// (tabIndex={-1}) so Tab still moves between actual form fields.
import {
  Button,
  Input,
  Tooltip,
  type InputProps,
} from "@fluentui/react-components";
import { EyeOffRegular, EyeRegular } from "@fluentui/react-icons";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { Translations } from "../i18n/locales/en";

type TK = keyof Translations;

export function PasswordInput(props: Omit<InputProps, "type">) {
  const { t } = useTranslation();
  const [visible, setVisible] = useState(true);
  const label = visible
    ? t("common.hidePassword" as TK)
    : t("common.showPassword" as TK);

  return (
    <Input
      {...props}
      type={visible ? "text" : "password"}
      autoComplete="off"
      contentAfter={
        <Tooltip content={label} relationship="label">
          <Button
            appearance="transparent"
            size="small"
            icon={visible ? <EyeOffRegular /> : <EyeRegular />}
            aria-label={label}
            tabIndex={-1}
            onClick={() => setVisible((v) => !v)}
          />
        </Tooltip>
      }
    />
  );
}
