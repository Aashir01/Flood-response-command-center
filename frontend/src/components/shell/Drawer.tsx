'use client';
// Native <dialog> side sheet: showModal() gives the focus trap and Esc; focus returns to the opener on close.
import { useEffect, useId, useRef, type ReactNode } from 'react';
import { IconClose } from '@/components/icons';
import { useLang } from '@/i18n/LangProvider';

export function Drawer({
  open,
  onClose,
  title,
  children,
  className = 'drawer',
  labelledBy,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  className?: string;
  labelledBy?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const autoId = useId();
  const titleId = labelledBy ?? `${autoId}-title`;
  const { t } = useLang();

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) {
      opener.current = document.activeElement as HTMLElement | null;
      if (typeof d.showModal === 'function') d.showModal();
      else d.setAttribute('open', '');
    } else if (!open && d.open) {
      if (typeof d.close === 'function') d.close();
      else d.removeAttribute('open');
    }
  }, [open]);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    const onNativeClose = () => {
      onClose();
      const o = opener.current;
      if (o && document.contains(o)) o.focus();
    };
    d.addEventListener('close', onNativeClose);
    return () => d.removeEventListener('close', onNativeClose);
  }, [onClose]);

  return (
    <dialog
      ref={ref}
      className={className}
      aria-labelledby={titleId}
      onCancel={(e) => {
        e.preventDefault();
        ref.current?.close();
      }}
      onClick={(e) => {
        // A click on the backdrop (the dialog element itself) closes it.
        if (e.target === ref.current) ref.current?.close();
      }}
    >
      {open ? (
        <>
          <div className="drawer__head">
            <h2 id={titleId}>{title}</h2>
            <button type="button" className="btn btn--ghost btn--small" style={{ marginInlineStart: 'auto' }} onClick={() => ref.current?.close()}>
              <IconClose />
              <span>{t('drawer.close')}</span>
            </button>
          </div>
          <div className="drawer__body">{children}</div>
        </>
      ) : null}
    </dialog>
  );
}
