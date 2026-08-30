import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from 'react';

import { BrandLockup } from '@/components/BrandLockup';
import styles from '@/components/ui.module.css';

export function AuthShell({ children }: { children: ReactNode }) {
  return (
    <div className={styles.authShell}>
      <div className={styles.card}>
        <div className={styles.brandRow}>
          <BrandLockup />
        </div>
        {children}
      </div>
    </div>
  );
}

export function Heading({ title, sub }: { title: string; sub?: ReactNode }) {
  return (
    <>
      <h1 className={styles.heading}>{title}</h1>
      {sub ? <p className={styles.sub}>{sub}</p> : null}
    </>
  );
}

export function Callout({
  kind = 'info',
  children,
}: {
  kind?: 'error' | 'info' | 'success';
  children: ReactNode;
}) {
  return (
    <div
      className={`${styles.callout} ${styles[kind]}`}
      role={kind === 'error' ? 'alert' : 'status'}
    >
      {children}
    </div>
  );
}

interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
}
export function Field({ label, id, ...rest }: FieldProps) {
  const fieldId = id ?? label.toLowerCase().replace(/\s+/g, '-');
  return (
    <label className={styles.field} htmlFor={fieldId}>
      <span>{label}</span>
      <input id={fieldId} {...rest} />
    </label>
  );
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost';
  busy?: boolean;
}
export function Button({ variant = 'primary', busy, disabled, children, ...rest }: ButtonProps) {
  const cls = variant === 'primary' ? styles.button : `${styles.button} ${styles[variant]}`;
  return (
    <button className={cls} disabled={disabled || busy} aria-busy={busy} {...rest}>
      {busy ? 'Working…' : children}
    </button>
  );
}

export function OrDivider({ children = 'or' }: { children?: ReactNode }) {
  return <div className={styles.row}>{children}</div>;
}

export function FootNote({ children }: { children: ReactNode }) {
  return <p className={styles.footNote}>{children}</p>;
}
