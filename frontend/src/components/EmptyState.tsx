// EmptyState — a centered placeholder for empty lists/tables. Centralizing it
// keeps every "nothing here yet" view visually identical (icon disc + title +
// muted description + optional action) instead of each page rolling its own.
import { Text, makeStyles, tokens } from "@fluentui/react-components";
import type { ReactNode } from "react";

const useStyles = makeStyles({
  root: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    textAlign: "center",
    gap: "8px",
    padding: "48px 16px",
  },
  iconCircle: {
    display: "grid",
    placeItems: "center",
    width: "56px",
    height: "56px",
    borderRadius: "50%",
    marginBottom: "4px",
    backgroundColor: tokens.colorNeutralBackground3,
    color: tokens.colorNeutralForeground3,
    fontSize: "28px",
  },
  description: {
    color: tokens.colorNeutralForeground3,
    maxWidth: "380px",
  },
  action: {
    marginTop: "8px",
  },
});

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
}) {
  const styles = useStyles();
  return (
    <div className={styles.root}>
      {icon ? <div className={styles.iconCircle}>{icon}</div> : null}
      <Text size={400} weight="semibold">
        {title}
      </Text>
      {description ? (
        <Text size={300} className={styles.description}>
          {description}
        </Text>
      ) : null}
      {action ? <div className={styles.action}>{action}</div> : null}
    </div>
  );
}
