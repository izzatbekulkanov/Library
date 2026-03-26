/* =============================================================
   confirm.js — ProAdmin Panel Promise-based confirm dialog
   Ishlatish:
     const ok = await confirmDialog({
         title:   "O'chirishni tasdiqlang",
         message: "Bu foydalanuvchini o'chirmoqchimisiz?",
         confirmText: "Ha, o'chirish",
         type: 'danger'   // 'danger' | 'warning' | 'info'
     });
     if (ok) { ... }
   ============================================================= */

(function () {
    'use strict';

    /* ── HTML qolipini yaratish ── */
    function buildOverlay() {
        const el = document.createElement('div');
        el.className = 'confirm-overlay';
        el.setAttribute('role', 'dialog');
        el.setAttribute('aria-modal', 'true');
        el.innerHTML = `
            <div class="confirm-dialog">
                <div class="confirm-icon-wrap danger" id="confirmIcon">
                    <i class="fa-solid fa-triangle-exclamation"></i>
                </div>
                <h3 class="confirm-title" id="confirmTitle">Tasdiqlang</h3>
                <p  class="confirm-body"  id="confirmBody">Bu amalni bajarishni xohlaysizmi?</p>
                <div class="confirm-actions">
                    <button class="confirm-btn confirm-btn-cancel" id="confirmCancel">
                        <i class="fa-solid fa-xmark"></i> Bekor qilish
                    </button>
                    <button class="confirm-btn confirm-btn-danger" id="confirmOk">
                        <i class="fa-solid fa-check" id="confirmOkIcon"></i>
                        <span id="confirmOkText">Ha, bajarish</span>
                    </button>
                </div>
            </div>`;
        document.body.appendChild(el);
        return el;
    }

    let overlay = null;
    let resolveFn = null;

    function getOverlay() {
        if (!overlay) overlay = buildOverlay();
        return overlay;
    }

    /* ── Icon va rang to'plami ── */
    const TYPE_CFG = {
        danger:  { icon: 'fa-triangle-exclamation', btnClass: 'confirm-btn-danger',  wrapClass: 'danger'  },
        warning: { icon: 'fa-triangle-exclamation', btnClass: 'confirm-btn-danger',  wrapClass: 'warning' },
        info:    { icon: 'fa-circle-info',          btnClass: 'confirm-btn-primary', wrapClass: 'info'    },
    };

    /* ── Asosiy funksiya ── */
    window.confirmDialog = function ({ title, message, confirmText, cancelText, type } = {}) {
        const ov     = getOverlay();
        const dialog = ov.querySelector('.confirm-dialog');
        const cfg    = TYPE_CFG[type] || TYPE_CFG.danger;

        /* Matnlarni to'ldirish */
        ov.querySelector('#confirmTitle').textContent    = title       || 'Tasdiqlang';
        ov.querySelector('#confirmBody').innerHTML       = message     || 'Davom etishni xohlaysizmi?';
        ov.querySelector('#confirmOkText').textContent   = confirmText || 'Ha, bajarish';
        if (cancelText) ov.querySelector('#confirmCancel').childNodes[1].textContent = ' ' + cancelText;

        /* Rang va ikon */
        const iconWrap = ov.querySelector('#confirmIcon');
        iconWrap.className = `confirm-icon-wrap ${cfg.wrapClass}`;
        iconWrap.querySelector('i').className = `fa-solid ${cfg.icon}`;

        const okBtn = ov.querySelector('#confirmOk');
        okBtn.className = `confirm-btn ${cfg.btnClass}`;

        /* Ko'rsatish */
        ov.classList.add('is-open');
        document.body.style.overflow = 'hidden';
        okBtn.focus();

        return new Promise(resolve => {
            resolveFn = resolve;
        });
    };

    /* ── Tugmalar ── */
    document.addEventListener('click', function (e) {
        if (!overlay) return;
        const ov = overlay;

        if (e.target.closest('#confirmOk')) {
            close(true);
        } else if (e.target.closest('#confirmCancel')) {
            close(false);
        } else if (e.target === ov) {
            /* Tashqi qismga bosish — silkitish */
            const d = ov.querySelector('.confirm-dialog');
            d.classList.remove('shake');
            void d.offsetWidth;   /* reflow */
            d.classList.add('shake');
        }
    });

    /* ESC tugmasi */
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && overlay && overlay.classList.contains('is-open')) {
            close(false);
        }
    });

    function close(result) {
        if (!overlay) return;
        overlay.classList.remove('is-open');
        document.body.style.overflow = '';
        if (resolveFn) { resolveFn(result); resolveFn = null; }
    }

})();
