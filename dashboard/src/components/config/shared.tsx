import { useState } from 'react';
import type { BotConfig } from '../../api/client';

// Subpanel props interface
export interface SubpanelProps {
  config: BotConfig;
  onChange: (section: keyof BotConfig, field: string, value: unknown) => void;
}

// Section accent colors
export const SECTION_COLORS = {
  mode: '#ffffff',
  discovery: '#8888a0',
  entry: '#4a9eff',
  position: '#00d4aa',
  exit: '#ffaa00',
  risk: '#ff4757',
} as const;

// Toggle switch component
export function Toggle({
  checked,
  onChange,
  label,
  disabled = false,
  activeColor = 'var(--accent-green)',
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  disabled?: boolean;
  activeColor?: string;
}) {
  return (
    <label
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '0.625rem',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.5 : 1,
      }}
    >
      <div
        onClick={() => !disabled && onChange(!checked)}
        style={{
          width: '32px',
          height: '18px',
          borderRadius: '9px',
          background: checked ? activeColor : 'var(--border)',
          position: 'relative',
          transition: 'background 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
          flexShrink: 0,
        }}
      >
        <div
          style={{
            width: '14px',
            height: '14px',
            borderRadius: '50%',
            background: 'white',
            position: 'absolute',
            top: '2px',
            left: checked ? '16px' : '2px',
            transition: 'left 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
            boxShadow: '0 1px 3px rgba(0,0,0,0.4)',
          }}
        />
      </div>
      <span style={{ fontSize: '0.75rem', color: 'var(--text-primary)', fontWeight: 500 }}>
        {label}
      </span>
    </label>
  );
}

// Segmented control for options like candle interval
export function SegmentedControl({
  value,
  options,
  onChange,
  label,
}: {
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
  label?: string;
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
      {label && (
        <span
          style={{
            fontSize: '0.625rem',
            textTransform: 'uppercase',
            letterSpacing: '0.1em',
            color: 'var(--text-muted)',
          }}
        >
          {label}
        </span>
      )}
      <div
        style={{
          display: 'flex',
          background: 'var(--bg-primary)',
          borderRadius: 'var(--radius-sm)',
          border: '1px solid var(--border)',
          padding: '2px',
          gap: '2px',
        }}
      >
        {options.map((opt) => (
          <button
            key={opt.value}
            onClick={() => onChange(opt.value)}
            style={{
              flex: 1,
              padding: '0.375rem 0.75rem',
              borderRadius: '3px',
              fontSize: '0.75rem',
              fontFamily: 'var(--font-mono)',
              fontWeight: 600,
              border: 'none',
              background: value === opt.value ? 'var(--accent-amber)' : 'transparent',
              color: value === opt.value ? '#0a0a0f' : 'var(--text-muted)',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );
}

// Multi-select dropdown for market types
export function MultiSelectDropdown({
  values,
  options,
  onChange,
  label,
}: {
  values: string[];
  options: { value: string; label: string }[];
  onChange: (v: string[]) => void;
  label?: string;
}) {
  const [isOpen, setIsOpen] = useState(false);

  const toggleOption = (optValue: string) => {
    if (values.includes(optValue)) {
      onChange(values.filter((v) => v !== optValue));
    } else {
      onChange([...values, optValue]);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', position: 'relative' }}>
      {label && (
        <span
          style={{
            fontSize: '0.625rem',
            textTransform: 'uppercase',
            letterSpacing: '0.1em',
            color: 'var(--text-muted)',
          }}
        >
          {label}
        </span>
      )}
      <button
        onClick={() => setIsOpen(!isOpen)}
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0.5rem 0.75rem',
          background: 'var(--bg-primary)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius-sm)',
          cursor: 'pointer',
          minWidth: '140px',
        }}
      >
        <span style={{ fontSize: '0.75rem', color: 'var(--text-primary)' }}>
          {values.length === 0
            ? 'Select...'
            : values.map((v) => options.find((o) => o.value === v)?.label || v).join(', ')}
        </span>
        <svg
          width="12"
          height="12"
          viewBox="0 0 12 12"
          fill="none"
          style={{
            transform: isOpen ? 'rotate(180deg)' : 'rotate(0deg)',
            transition: 'transform 0.2s',
            color: 'var(--text-muted)',
          }}
        >
          <path
            d="M2.5 4.5L6 8L9.5 4.5"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
      {isOpen && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            right: 0,
            marginTop: '4px',
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-sm)',
            zIndex: 100,
            boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
          }}
        >
          {options.map((opt) => (
            <label
              key={opt.value}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
                padding: '0.5rem 0.75rem',
                cursor: 'pointer',
                borderBottom: '1px solid var(--border-subtle)',
              }}
              onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--bg-elevated)')}
              onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
            >
              <input
                type="checkbox"
                checked={values.includes(opt.value)}
                onChange={() => toggleOption(opt.value)}
                style={{ accentColor: 'var(--accent-green)' }}
              />
              <span style={{ fontSize: '0.75rem', color: 'var(--text-primary)' }}>{opt.label}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

// Inline editable value
export function InlineValue({
  label,
  value,
  onChange,
  suffix = '',
  type = 'number',
  accentColor = 'var(--accent-blue)',
}: {
  label: string;
  value: string | number;
  onChange: (v: string | number) => void;
  suffix?: string;
  type?: 'number' | 'text';
  accentColor?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [tempValue, setTempValue] = useState(String(value));

  const handleSave = () => {
    setEditing(false);
    const newValue = type === 'number' ? parseFloat(tempValue) || 0 : tempValue;
    if (newValue !== value) {
      onChange(newValue);
    }
  };

  if (editing) {
    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0.25rem 0',
        }}
      >
        <span style={{ fontSize: '0.6875rem', color: 'var(--text-muted)', minWidth: '70px' }}>
          {label}
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
          <input
            type={type}
            value={tempValue}
            onChange={(e) => setTempValue(e.target.value)}
            onBlur={handleSave}
            onKeyDown={(e) => e.key === 'Enter' && handleSave()}
            autoFocus
            style={{
              width: '70px',
              padding: '0.25rem 0.375rem',
              fontSize: '0.75rem',
              textAlign: 'right',
              background: 'var(--bg-primary)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--text-primary)',
            }}
          />
          <span style={{ fontSize: '0.6875rem', color: 'var(--text-muted)', minWidth: '16px' }}>
            {suffix}
          </span>
        </div>
      </div>
    );
  }

  return (
    <div
      onClick={() => {
        setTempValue(String(value));
        setEditing(true);
      }}
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        cursor: 'pointer',
        padding: '0.25rem 0',
        borderRadius: 'var(--radius-sm)',
        transition: 'background 0.1s',
      }}
      onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--bg-elevated)')}
      onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
    >
      <span style={{ fontSize: '0.6875rem', color: 'var(--text-muted)' }}>{label}</span>
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '0.75rem',
          color: accentColor,
          fontWeight: 500,
        }}
      >
        {value}
        {suffix && <span style={{ color: 'var(--text-muted)', marginLeft: '1px' }}>{suffix}</span>}
      </span>
    </div>
  );
}

// Subpanel card wrapper
export function SubpanelCard({
  title,
  accentColor,
  children,
}: {
  title: string;
  accentColor: string;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        background: 'var(--bg-card)',
        borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border)',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          padding: '0.5rem 0.75rem',
          borderBottom: '1px solid var(--border)',
          display: 'flex',
          alignItems: 'center',
          gap: '0.5rem',
          background: 'var(--bg-elevated)',
        }}
      >
        <div
          style={{
            width: '3px',
            height: '12px',
            borderRadius: '2px',
            background: accentColor,
            opacity: 0.8,
          }}
        />
        <span
          style={{
            fontSize: '0.625rem',
            textTransform: 'uppercase',
            letterSpacing: '0.1em',
            color: 'var(--text-secondary)',
            fontWeight: 600,
          }}
        >
          {title}
        </span>
      </div>
      <div style={{ padding: '0.75rem' }}>{children}</div>
    </div>
  );
}
