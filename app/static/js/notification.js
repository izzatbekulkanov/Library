/* =============================================================
   notification.js — ProAdmin Panel global toast bildirishnoma
   Ishlatish:
     notify('Muvaffaqiyat!', 'Foydalanuvchi saqlandi.', 'success')
     notify('Xato!', 'Biror narsa noto\'g\'ri ketdi.', 'error')
     notify('Ogohlantirish', 'Iltimos, emailni to\'ldiring.', 'warning')
     notify('Ma\'lumot', 'Sahifa yangilandi.', 'info')
   ============================================================= */

(function () {
    'use strict';

    /* ── Konteyner yaratish ── */
    let container = document.getElementById('notification-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'notification-container';
        document.body.appendChild(container);
    }

    /* ── Ikonkalar ── */
    const ICONS = {
        success: '<i class="fa-solid fa-check"></i>',
        error:   '<i class="fa-solid fa-xmark"></i>',
        warning: '<i class="fa-solid fa-triangle-exclamation"></i>',
        info:    '<i class="fa-solid fa-circle-info"></i>',
    };

    /* ── Sarlavhalar ── */
    const TITLES = {
        success: 'Muvaffaqiyat',
        error:   'Xatolik',
        warning: 'Ogohlantirish',
        info:    'Ma\'lumot',
    };

    /* ── Asosiy funksiya ── */
    window.notify = function (title, message, type = 'info', duration = 4000) {
        type = ['success', 'error', 'warning', 'info'].includes(type) ? type : 'info';

        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.setAttribute('role', 'alert');
        toast.setAttribute('aria-live', 'polite');

        toast.innerHTML = `
            <div class="toast-icon">${ICONS[type]}</div>
            <div class="toast-body">
                <p class="toast-title">${escHtml(title || TITLES[type])}</p>
                ${message ? `<p class="toast-message">${escHtml(message)}</p>` : ''}
            </div>
            <button class="toast-close" aria-label="Yopish">
                <i class="fa-solid fa-xmark"></i>
            </button>
            <div class="toast-progress" style="animation-duration:${duration}ms;"></div>
        `;

        /* Yopish tugmasi */
        toast.querySelector('.toast-close').addEventListener('click', () => hide(toast));

        container.appendChild(toast);

        /* Avtomatik yopish */
        const timer = setTimeout(() => hide(toast), duration);

        /* Sichqon ustida tursa to'xtash */
        toast.addEventListener('mouseenter', () => {
            clearTimeout(timer);
            const bar = toast.querySelector('.toast-progress');
            if (bar) bar.style.animationPlayState = 'paused';
        });
        toast.addEventListener('mouseleave', () => {
            hide(toast, 1200);
        });

        return toast;
    };

    /* ─── Qisqa yordamchi funksiyalar ─── */
    window.notifySuccess = (msg, title) => notify(title || 'Muvaffaqiyat', msg, 'success');
    window.notifyError   = (msg, title) => notify(title || 'Xatolik',       msg, 'error');
    window.notifyWarn    = (msg, title) => notify(title || 'Ogohlantirish', msg, 'warning');
    window.notifyInfo    = (msg, title) => notify(title || "Ma'lumot",      msg, 'info');
    window.showNotification = function (title, message, type = 'info', duration = 4000) {
        return notify(title, message, type, duration);
    };

    /* ─── Yashirish ─── */
    function hide(toast, delay = 0) {
        setTimeout(() => {
            toast.classList.add('toast-hiding');
            toast.addEventListener('animationend', () => toast.remove(), { once: true });
        }, delay);
    }

    /* ─── HTML escape ─── */
    function escHtml(str) {
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    /* ─── Flash xabarlarini avtomatik ko'rsatish ─── */
    document.addEventListener('DOMContentLoaded', function () {
        const flash = document.getElementById('flash-data');
        if (flash) {
            const type    = flash.dataset.type    || 'info';
            const title   = flash.dataset.title   || '';
            const message = flash.dataset.message || '';
            if (title || message) {
                setTimeout(() => notify(title, message, type), 300);

                /* ── URL dan flash query paramlarini tozalash ──
                   Sahifa yangilanganda notification qayta chiqmasin */
                try {
                    const url = new URL(window.location.href);
                    url.searchParams.delete('flash_type');
                    url.searchParams.delete('flash_title');
                    url.searchParams.delete('flash_msg');
                    const clean = url.pathname + (url.search || '') + (url.hash || '');
                    history.replaceState(null, '', clean);
                } catch (_) {}
            }
        }
    });

})();
