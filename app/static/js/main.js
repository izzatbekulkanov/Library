/**
 * Main JS Logic - FastAPI Glassmorphism UI
 */

const THEME_STORAGE_KEY = 'proadmin-theme';

function resolveTheme() {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === 'light' || stored === 'dark') return stored;
    return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

function applyTheme(theme) {
    const picked = theme === 'light' ? 'light' : 'dark';
    const html = document.documentElement;
    html.classList.remove('theme-light', 'theme-dark', 'dark');
    html.classList.add(`theme-${picked}`);
    if (picked === 'dark') html.classList.add('dark');
    html.setAttribute('data-theme', picked);
    localStorage.setItem(THEME_STORAGE_KEY, picked);
    updateThemeToggleUi(picked);
}

function updateThemeToggleUi(theme) {
    const btn = document.getElementById('themeToggleBtn');
    const icon = document.getElementById('themeToggleIcon');
    if (!btn || !icon) return;

    if (theme === 'light') {
        icon.classList.remove('fa-moon');
        icon.classList.add('fa-sun');
        btn.setAttribute('title', 'Tungi rejimga o\'tish');
        btn.setAttribute('aria-label', 'Tungi rejimga o\'tish');
    } else {
        icon.classList.remove('fa-sun');
        icon.classList.add('fa-moon');
        btn.setAttribute('title', 'Kunduzgi rejimga o\'tish');
        btn.setAttribute('aria-label', 'Kunduzgi rejimga o\'tish');
    }
}

function initThemeToggle() {
    const btn = document.getElementById('themeToggleBtn');
    const currentTheme = resolveTheme();
    applyTheme(currentTheme);
    if (!btn) return;
    btn.addEventListener('click', () => {
        const activeTheme = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
        applyTheme(activeTheme === 'light' ? 'dark' : 'light');
    });
}

// 1. Loader Logic
function showLoader(event, url) {
    // Agar maxsus url berilgan bo'lsa, defolt holatni (havolaga o'tishni) kechiktirish
    if(event && url) event.preventDefault();
    const loader = document.getElementById('pageLoader');
    
    if (loader) {
        loader.classList.add('active');
        
        // Form submit kabi processlar uchun url bo'lmasa, shunchaki loaderni yoqamiz va o'zi jo'natadi
        if (url && url !== '#') {
            setTimeout(() => {
                loader.classList.remove('active');
                window.location.href = url;
            }, 800);
        } else if (!url) {
            // Agar form submit bo'lsa (url yo'q), birozdan so'ng loaderni o'zi o'chishi uchun qayta tiklaymiz (ixtiyoriy)
        }
    }
}

// 2. Mobil Sidebar Logic
function toggleSidebarMenu() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');
    
    if (sidebar && overlay) {
        // requestAnimationFrame brauzerning tez ishlashi uchun animatsiyalarni navbatga qo'yadi.
        requestAnimationFrame(() => {
            sidebar.classList.toggle('-translate-x-full');
            overlay.classList.toggle('hidden');
        });
    }
}

// 3. Desktop Sidebar Collapse Logic (Animatsiyali - Optimallashtirilgan)
function toggleSidebarCollapse() {
    const sidebar = document.getElementById('sidebar');
    const texts = document.querySelectorAll('.menu-text, .sidebar-text, .logo-text, .menu-label, .user-info');
    const icon = document.getElementById('collapseIcon');
    const logoContainer = document.getElementById('logo-container');
    const profileBtn = document.getElementById('userProfileBtn');
    const profileMenu = document.getElementById('userProfileMenu');
    const profileChevron = document.getElementById('userProfileChevron');
    
    if (!sidebar) return;

    requestAnimationFrame(() => {
        if (sidebar.classList.contains('w-64')) {
            // Qisqartirish amallari
            sidebar.classList.replace('w-64', 'w-20');
            
            // Matnlarni yashirish
            texts.forEach(el => {
                el.classList.add('opacity-0');
                // Timeout faqat stilni olib tashlash uchun ishlatiladi, dom blockini ushlamaydi.
                setTimeout(() => el.classList.add('hidden'), 150);
            });
            
            // Ikonkani aylantirish
            if (icon) icon.classList.add('rotate-180');
            if (logoContainer) logoContainer.classList.add('justify-center');
            if (profileBtn) profileBtn.classList.add('justify-center', 'px-0');
            if (profileMenu) profileMenu.classList.add('hidden');
            if (profileChevron) profileChevron.classList.remove('rotate-180');
            
        } else {
            // Kengaytirish amallari
            sidebar.classList.replace('w-20', 'w-64');
            
            // Matnlarni ko'rsatish
            texts.forEach(el => {
                el.classList.remove('hidden');
                // Qayta tiklashni brauzer re-paintga moslash (0ms delay bloki)
                setTimeout(() => el.classList.remove('opacity-0'), 10);
            });
            
            // Ikonkani qaytarish
            if (icon) icon.classList.remove('rotate-180');
            if (logoContainer) logoContainer.classList.remove('justify-center');
            if (profileBtn) profileBtn.classList.remove('justify-center', 'px-0');
        }
    });
}

document.addEventListener('DOMContentLoaded', () => {
    initThemeToggle();

    const profileBtn = document.getElementById('userProfileBtn');
    const profileMenu = document.getElementById('userProfileMenu');
    const profileChevron = document.getElementById('userProfileChevron');

    if (!profileBtn || !profileMenu) return;

    const closeProfileMenu = () => {
        profileMenu.classList.add('hidden');
        profileBtn.setAttribute('aria-expanded', 'false');
        if (profileChevron) profileChevron.classList.remove('rotate-180');
    };

    profileBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const willOpen = profileMenu.classList.contains('hidden');
        if (willOpen) {
            profileMenu.classList.remove('hidden');
            profileBtn.setAttribute('aria-expanded', 'true');
            if (profileChevron) profileChevron.classList.add('rotate-180');
        } else {
            closeProfileMenu();
        }
    });

    profileMenu.addEventListener('click', (e) => e.stopPropagation());
    document.addEventListener('click', closeProfileMenu);
});

// 4. Universal delete confirmation for delete links (POST by default, GET optional)
async function confirmDelete(itemName, deleteUrl, method = 'POST') {
    const name = (itemName || "element").toString();
    const normalizedMethod = String(method || 'POST').toUpperCase();
    let ok = true;

    if (typeof confirmDialog === 'function') {
        ok = await confirmDialog({
            title: "O'chirishni tasdiqlang",
            message: `<strong>${name}</strong> ni o'chirmoqchimisiz? Bu amalni bekor qilib bo'lmaydi.`,
            confirmText: "Ha, o'chirish",
            type: 'danger'
        });
    } else {
        ok = window.confirm(`${name} ni o'chirmoqchimisiz?`);
    }

    if (!ok) return;
    const loader = document.getElementById('pageLoader');
    if (loader) loader.classList.add('active');

    if (normalizedMethod === 'GET') {
        window.location.href = deleteUrl;
        return;
    }

    const form = document.createElement('form');
    form.method = 'POST';
    form.action = deleteUrl;
    form.style.display = 'none';
    document.body.appendChild(form);
    form.submit();
}
