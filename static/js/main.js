let sidebarOpen = false;
let aiStep = 0; // 0 = Auto-Fill, 1 = Summarize, 2 = Save
let chartsInstance = [];

// =====================================================================
// --- SweetAlert2 Small Center Alert (Reusable) ---
// =====================================================================
const CenterAlert = Swal.mixin({
    showConfirmButton: false,
    timer: 3000,
    timerProgressBar: true,
    width: '24rem',
    padding: '1.5rem',
    customClass: {
        popup: 'rounded-2xl shadow-xl border border-gray-100 text-sm',
        title: 'text-gray-800 font-semibold text-base m-0',
        icon: 'text-brand' 
    },
    didOpen: (popup) => {
        popup.addEventListener('mouseenter', Swal.stopTimer)
        popup.addEventListener('mouseleave', Swal.resumeTimer)
    }
});

function getSelectedRole() {
    if (typeof window.SENTIMENTAL_ROLE !== 'undefined' && window.SENTIMENTAL_ROLE) {
        return window.SENTIMENTAL_ROLE;
    }
    return localStorage.getItem('sentimentalRole') || 'responder';
}

function applySelectedRole(role) {
    localStorage.setItem('sentimentalRole', role);

    document.querySelectorAll('.nav-responder').forEach(el => {
        el.classList.toggle('hidden', role !== 'responder');
    });
    document.querySelectorAll('.nav-admin').forEach(el => {
        el.classList.toggle('hidden', role !== 'admin');
    });

    const roleLabel = document.getElementById('header-user-role');
    if (roleLabel) {
        roleLabel.textContent = role === 'admin' ? 'Administrator' : 'Responder';
    }
}

function goHome() {
    const role = getSelectedRole();
    if (role === 'admin') {
        window.location.href = '/dashboard/admin/index/';
    } else {
        window.location.href = '/dashboard/';
    }
}

function handleLogin() {
    const roleSelect = document.getElementById('login-role');
    const role = roleSelect ? roleSelect.value : 'responder';
    applySelectedRole(role);
    window.location.href = role === 'admin' ? '/dashboard/admin/index/' : '/dashboard/';
}

function handleLogout() {
    localStorage.removeItem('sentimentalRole');
    window.location.href = '/accounts/logout/';
}

function confirmLogout(event) {
    event.preventDefault();
    const logoutUrl = event.currentTarget ? event.currentTarget.getAttribute('href') : '/accounts/logout/';

    // Using a custom styled Swal for the logout confirmation
    Swal.fire({
        title: 'Logout?',
        text: 'Are you sure you want to log out?',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Logout',
        cancelButtonText: 'Cancel',
        confirmButtonColor: '#dc2626',
        cancelButtonColor: '#6b7280',
        width: '24rem',
        padding: '1.5rem',
        customClass: {
            popup: 'rounded-2xl shadow-xl border border-gray-100 text-sm',
            title: 'text-gray-800 font-semibold text-base m-0',
            confirmButton: 'rounded-lg px-4 py-2 text-sm font-bold',
            cancelButton: 'rounded-lg px-4 py-2 text-sm font-bold'
        }
    }).then((result) => {
        if (result.isConfirmed) {
            window.location.href = logoutUrl;
        }
    });
}

function injectPasswordToggleStyles() {
    if (document.getElementById('password-toggle-styles')) return;

    const style = document.createElement('style');
    style.id = 'password-toggle-styles';
    style.textContent = `
        .password-toggle-wrapper { position: relative; display: inline-block; width: 100%; }
        .password-toggle-wrapper input { padding-right: 3.5rem; }
        .password-toggle-btn {
            position: absolute;
            top: 50%;
            right: 0.75rem;
            transform: translateY(-50%);
            border: none;
            background: transparent;
            color: #475569;
            cursor: pointer;
            width: 2.5rem;
            height: 2.5rem;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 0;
            line-height: 1;
            font-size: 1.2rem;
        }
        .password-toggle-btn svg {
            display: block;
            width: 1.2rem;
            height: 1.2rem;
        }
        .password-toggle-btn:focus {
            outline: 2px solid rgba(0, 166, 126, 0.5);
            outline-offset: 2px;
        }
        .password-toggle-btn:hover { color: #0f766e; }
    `;
    document.head.appendChild(style);
}

function createEyeIcon(isVisible) {
    if (isVisible) {
        return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><path d="M17.94 17.94A10.94 10.94 0 0 1 12 20c-7 0-11-8-11-8a17.67 17.67 0 0 1 5-5.92"/><path d="M1 1l22 22"/><path d="M9.88 9.88A3 3 0 0 0 14.12 14.12"/><path d="M14.06 9.06A3 3 0 0 0 9.94 14.18"/></svg>';
    }
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8S1 12 1 12z"/><circle cx="12" cy="12" r="3"/></svg>';
}

function attachPasswordToggle(input, toggle) {
    if (!toggle || !input) return;
    toggle.classList.add('password-toggle-btn');
    toggle.type = 'button';
    toggle.setAttribute('aria-label', 'Show password');
    toggle.setAttribute('title', 'Show password');
    toggle.innerHTML = createEyeIcon(false);

    toggle.addEventListener('click', () => {
        const isHidden = input.type === 'password';
        input.type = isHidden ? 'text' : 'password';
        toggle.innerHTML = createEyeIcon(isHidden);
        toggle.setAttribute('aria-label', isHidden ? 'Hide password' : 'Show password');
        toggle.setAttribute('title', isHidden ? 'Hide password' : 'Show password');
        input.focus();
    });
}

function initPasswordToggles() {
    injectPasswordToggleStyles();

    document.querySelectorAll('input[type="password"]').forEach(input => {
        const existingWrapper = input.closest('.password-toggle-wrapper');
        let wrapper = existingWrapper;

        if (!wrapper) {
            wrapper = document.createElement('div');
            wrapper.className = 'password-toggle-wrapper';
            input.parentNode.insertBefore(wrapper, input);
            wrapper.appendChild(input);
        }

        let toggle = wrapper.querySelector('.password-toggle-btn');
        if (!toggle) {
            toggle = document.createElement('button');
            wrapper.appendChild(toggle);
        }

        attachPasswordToggle(input, toggle);
    });
}

function updatePasswordRequirements(password) {
    const commonPasswords = ['password', '12345678', 'qwerty', 'letmein', '123456789'];
    const checks = [
        { id: 'req-length', valid: password.length >= 8 },
        { id: 'req-not-numeric', valid: password.length > 0 && !/^\d+$/.test(password) },
        { id: 'req-not-common', valid: password.length > 0 && !commonPasswords.includes(password.toLowerCase()) },
        { id: 'req-not-similar', valid: password.length > 0 && !/(password|123456|qwerty|admin|user)/i.test(password) },
    ];

    checks.forEach(check => {
        const el = document.getElementById(check.id);
        if (!el) return;
        el.classList.toggle('text-emerald-700', check.valid);
        el.classList.toggle('text-slate-500', !check.valid);
        const status = el.querySelector('.requirement-status');
        if (status) status.textContent = check.valid ? '✓' : '✕';
    });

    return checks.every(check => check.valid);
}

function initPasswordRequirementHints() {
    const passwordInput = document.getElementById('id_new_password1');
    const confirmInput = document.getElementById('id_new_password2');
    const form = document.getElementById('password-reset-confirm-form');

    if (!passwordInput || !form) return;

    passwordInput.addEventListener('input', () => {
        updatePasswordRequirements(passwordInput.value);
    });

    form.addEventListener('submit', (event) => {
        const isValid = updatePasswordRequirements(passwordInput.value);
        const passwordsMatch = passwordInput.value === (confirmInput ? confirmInput.value : '');

        if (!isValid || !passwordsMatch) {
            event.preventDefault();
            let message = 'Please fix the password requirements before continuing.';
            if (!passwordsMatch) {
                message = 'Passwords do not match. Please confirm your new password.';
            }
            CenterAlert.fire({
                icon: 'error',
                title: 'Invalid password'
            });
        }
    });

    updatePasswordRequirements(passwordInput.value);
}

function ready(callback) {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', callback);
    } else {
        callback();
    }
}

ready(() => {
    initPasswordToggles();
    initPasswordRequirementHints();
});

// =====================================================================
// --- Skeleton Loading Overlay (navigation feedback) ---
//
// Navigation is normally a full page load (and, while a call is held, an
// in-place swap - see "Recording-safe navigation" below). In both cases the
// browser keeps painting the current page until the new one is ready, so a
// skeleton shown the moment a link is clicked fills that gap with feedback.
//
// The skeleton is scoped to #tab-content-container so the header, the
// sidebar and the persistent panel stay visible, and it is matched to
// the destination URL so it mirrors the layout of the incoming page.
// =====================================================================

const SK_BAR = 'rounded bg-gray-200/80 animate-pulse';
const SK_SOFT = 'rounded bg-gray-100 animate-pulse';

function skBar(w, h) {
    return `<div class="${h || 'h-3'} ${w} ${SK_BAR}"></div>`;
}

function skCard(inner, style, cls) {
    return `<div class="bg-white border border-gray-100 rounded-2xl shadow-sm p-5 ${cls || ''}" ${style ? `style="${style}"` : ''}>${inner}</div>`;
}

function skTable(cols, rows) {
    const head = `<div class="flex items-center gap-4 pb-3 border-b border-gray-100">${cols.map(c => skBar(c)).join('')}</div>`;
    const body = Array.from({ length: rows }, () =>
        `<div class="flex items-center gap-4 py-3 border-b border-gray-50">${cols.map(c => skBar(c, 'h-4')).join('')}</div>`).join('');
    return head + body;
}

function skPagination() {
    return `<div class="flex items-center justify-between pt-4">
        ${skBar('w-24')}
        <div class="flex gap-2">${skBar('w-8', 'h-8')}${skBar('w-8', 'h-8')}${skBar('w-8', 'h-8')}</div>
    </div>`;
}

function skStat() {
    return skCard(`${skBar('w-20')}<div class="mt-2 h-8 w-16 rounded-lg bg-gray-200/80 animate-pulse"></div><div class="mt-3 h-2 w-full ${SK_SOFT}"></div>`, 'h-28');
}

function skDoughnut() {
    return skCard(`<div class="mx-auto mt-2 h-28 w-28 rounded-full border-[12px] border-gray-100 animate-pulse"></div>`, 'h-48');
}

function skProgress() {
    return `<div class="space-y-2">${skBar('w-28')}<div class="h-2 w-full rounded-full bg-gray-100 animate-pulse"></div></div>`;
}

function skChip(w) {
    return `<div class="h-10 ${w} rounded-lg bg-gray-100 animate-pulse"></div>`;
}

function skTitle(w) {
    return `<div class="h-9 ${w} rounded-lg bg-gray-200/80 animate-pulse"></div>`;
}

function skCalendarGrid() {
    const days = Array.from({ length: 7 }, () => `<div class="h-2 w-10 mx-auto ${SK_BAR}"></div>`).join('');
    const cells = Array.from({ length: 35 }, () =>
        `<div class="h-20 rounded-xl border border-gray-100 bg-white p-2"><div class="h-2 w-6 ${SK_BAR}"></div></div>`).join('');
    return `<div class="grid grid-cols-7 gap-2 mb-2">${days}</div><div class="grid grid-cols-7 gap-2">${cells}</div>`;
}

function skMap() {
    return `<div class="relative h-[28rem] w-full rounded-2xl bg-gray-100 overflow-hidden animate-pulse">
        <div class="absolute top-1/4 left-1/4 h-4 w-4 rounded-full bg-brand/40 animate-ping"></div>
        <div class="absolute top-1/2 right-1/3 h-5 w-5 rounded-full bg-red-400/50 animate-ping"></div>
        <div class="absolute bottom-1/3 left-1/2 h-4 w-4 rounded-full bg-orange-300/50 animate-ping"></div>
        <div class="absolute bottom-4 right-4 bg-white rounded-xl border border-gray-200 p-3 space-y-2">
            <div class="h-2 w-24 ${SK_BAR}"></div>
            <div class="h-2 w-16 ${SK_BAR}"></div>
        </div>
    </div>`;
}

function skInputRow(count, wide) {
    return Array.from({ length: count }, (_, i) =>
        `<div class="space-y-1 ${i === count - 1 && wide ? 'col-span-2' : ''}">${skBar('w-20', 'h-2')}${skBar('w-full', 'h-9')}</div>`).join('');
}

// --- Per-page skeletons ---

function skAdminDashboard() {
    return `
    ${skTitle('w-72')}
    <div class="flex gap-3">${skChip('w-32')}${skChip('w-40')}${skChip('w-48')}</div>
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">${skStat()}${skStat()}${skStat()}${skStat()}</div>
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">${skDoughnut()}${skDoughnut()}${skDoughnut()}</div>
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4 items-start">
        <div class="lg:col-span-2">${skCard(skTable(['w-1/5', 'w-1/4', 'w-1/3', 'w-1/6'], 5), 'min-h-[16rem]')}</div>
        ${skCard(`<div class="space-y-6">${skBar('w-48', 'h-4')}${skProgress()}${skProgress()}${skProgress()}</div>`)}
    </div>`;
}

function skResponderDashboard() {
    return `
    <div class="flex items-center justify-between">
        ${skTitle('w-64')}
        <div class="h-10 w-32 rounded-lg bg-gray-100 animate-pulse"></div>
    </div>
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">${skDoughnut()}${skDoughnut()}${skDoughnut()}</div>
    <div class="flex flex-col lg:flex-row gap-4 items-stretch">
        <div class="flex-1">${skCard(`${skBar('w-40', 'h-4')}<div class="mt-4 h-48 w-full rounded-xl bg-gray-100 animate-pulse"></div>`)}</div>
        <div class="w-full lg:w-48">${skCard(`<div class="space-y-4">${skBar('w-20', 'h-4')}${skProgress()}${skProgress()}</div>`)}</div>
    </div>
    ${skCard(`${skBar('w-48', 'h-4')}<div class="mt-4">${skTable(['w-1/4', 'w-1/6', 'w-1/4', 'w-1/5', 'w-1/6'], 4)}</div>`)}`;
}

function skForecast() {
    return `
    <div class="flex items-center justify-between">
        ${skTitle('w-72')}
        <div class="flex gap-2">${skChip('w-24')}${skChip('w-24')}</div>
    </div>
    ${skCard(`<div class="flex items-center gap-4">${skChip('w-44')}${skChip('w-40')}</div>`)}
    <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">${Array.from({ length: 4 }, () =>
        skCard(`${skBar('w-24')}<div class="mt-2 h-4 w-32 rounded bg-gray-200/80 animate-pulse"></div>`, 'h-20')).join('')}</div>
    ${skCard(`${skBar('w-40', 'h-4')}<div class="mt-4 h-72 w-full rounded-xl bg-gray-100 animate-pulse"></div>`, 'h-[26rem]')}
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">${Array.from({ length: 3 }, () =>
        skCard(`${skBar('w-28')}<div class="mt-3 space-y-2">${skBar('w-full')}${skBar('w-3/4')}${skBar('w-1/2')}</div>`)).join('')}</div>
    ${skCard(`${skBar('w-56', 'h-4')}<div class="mt-4">${skTable(['w-1/4', 'w-3/12', 'w-3/12', 'w-2/12'], 4)}</div>`)}`;
}

function skHeatmap() {
    return `
    <div class="flex items-center justify-between">
        ${skTitle('w-72')}
        <div class="flex gap-3">${skChip('w-32')}${skChip('w-32')}</div>
    </div>
    ${skMap()}
    ${skCard(`${skBar('w-40', 'h-4')}<div class="mt-4">${skTable(['w-1/4', 'w-1/6', 'w-1/6', 'w-1/6', 'w-1/6'], 5)}</div>`)}`;
}

function skAdminCalendar() {
    return `
    <div class="flex items-center justify-between">
        ${skTitle('w-80')}
        <div class="h-10 w-28 rounded-xl bg-gray-200/80 animate-pulse"></div>
    </div>
    ${skCard(`<div class="flex items-center gap-4"><div class="h-10 w-10 rounded-full bg-brand/20 animate-pulse"></div><div class="flex-1 space-y-2">${skBar('w-56')}${skBar('w-40', 'h-2')}</div></div>`)}
    <div class="grid grid-cols-2 lg:grid-cols-5 gap-4">${Array.from({ length: 5 }, () => skStat()).join('')}</div>
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4 items-start">
        <div class="lg:col-span-2 space-y-4">
            ${skCard(`<div class="space-y-4">${skBar('w-32', 'h-4')}<div class="grid grid-cols-2 gap-4">${skInputRow(4)}${skInputRow(2, true)}</div><div class="h-10 w-44 rounded-lg bg-gray-200/80 animate-pulse"></div></div>`)}
            ${skCard(`<div class="space-y-4">${skBar('w-44', 'h-4')}${Array.from({ length: 4 }, () =>
                `<div class="flex items-center gap-3"><div class="h-10 w-10 rounded-full bg-gray-100 animate-pulse"></div><div class="flex-1 space-y-1">${skBar('w-36')}${skBar('w-24', 'h-2')}</div>${skBar('w-16', 'h-6')}</div>`).join('')}</div>`)}
        </div>
        <div class="space-y-4">
            ${skCard(`<div class="space-y-4">${skBar('w-36', 'h-4')}${Array.from({ length: 3 }, () =>
                `<div class="rounded-xl border border-gray-100 p-3 space-y-2">${skBar('w-28')}<div class="flex gap-2">${skBar('w-16', 'h-7')}${skBar('w-16', 'h-7')}</div></div>`).join('')}</div>`, 'min-h-[16rem]')}
            ${skCard(`<div class="space-y-4">${skBar('w-36', 'h-4')}${Array.from({ length: 5 }, () => skBar('w-full', 'h-7')).join('')}</div>`, 'min-h-[12rem]')}
        </div>
    </div>`;
}

function skResponderCalendar() {
    return `
    <div class="flex items-center justify-between">
        ${skTitle('w-64')}
        <div class="h-10 w-40 rounded-xl bg-gray-200/80 animate-pulse"></div>
    </div>
    ${skCard(skCalendarGrid())}
    ${skCard(`${skBar('w-44', 'h-4')}<div class="mt-4">${skTable(['w-1/4', 'w-1/4', 'w-1/4', 'w-1/6'], 3)}</div>`)}`;
}

function skAccountsManage() {
    return `
    <div class="flex items-center justify-between">
        ${skTitle('w-56')}
        <div class="h-10 w-36 rounded-xl bg-gray-200/80 animate-pulse"></div>
    </div>
    ${skCard(`<div class="flex gap-3 mb-5">${skChip('w-64')}${skChip('w-32')}</div>${skTable(['w-1/3', 'w-1/3', 'w-1/6', 'w-1/6'], 6)}${skPagination()}`)}`;
}

function skProfile() {
    return `
    ${skTitle('w-64')}
    <div class="grid grid-cols-1 lg:grid-cols-4 gap-6 items-start">
        ${skCard(`<div class="flex flex-col items-center space-y-3">
            <div class="h-24 w-24 rounded-full bg-gray-100 animate-pulse"></div>
            ${skBar('w-28')}${skBar('w-20', 'h-2')}
            <div class="mt-2 h-9 w-28 rounded-lg bg-gray-100 animate-pulse"></div>
        </div>`, '', 'lg:col-span-1')}
        <div class="lg:col-span-3">${skCard(`<div class="space-y-5">
            ${skBar('w-40', 'h-4')}
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">${skInputRow(4)}${skInputRow(1, true)}</div>
            <div class="h-px bg-gray-100"></div>
            ${skBar('w-32', 'h-4')}
            <div class="h-10 w-44 rounded-lg bg-gray-100 animate-pulse"></div>
            <div class="h-10 w-36 rounded-lg bg-gray-200/80 animate-pulse"></div>
        </div>`)}</div>
    </div>`;
}

function skReferralsManage() {
    return `
    ${skTitle('w-72')}
    ${skCard(`${skBar('w-48', 'h-4')}<div class="flex gap-3 my-4">${skChip('w-full')}${skChip('w-28')}</div>${skTable(['w-1/4', 'w-1/5', 'w-1/5', 'w-1/6', 'w-1/6'], 5)}${skPagination()}`)}
    ${skCard(`${skBar('w-36', 'h-4')}<div class="flex gap-3 my-4">${skChip('w-40')}${skChip('w-full')}</div>${skTable(['w-1/4', 'w-1/5', 'w-1/5', 'w-1/6', 'w-1/6'], 5)}${skPagination()}`)}`;
}

function skReferralsDirectory() {
    return `
    <div class="flex items-center justify-between">
        ${skTitle('w-64')}
        ${skChip('w-44')}
    </div>
    ${skCard(`${skChip('w-full')}<div class="mt-5">${skTable(['w-1/3', 'w-1/4', 'w-1/3'], 6)}</div>${skPagination()}`)}`;
}

function skCallersTable() {
    return `
    <div class="flex items-center justify-between">
        ${skTitle('w-56')}
        ${skChip('w-36')}
    </div>
    ${skCard(`${skChip('w-full')}<div class="mt-5">${skTable(['w-1/4', 'w-1/6', 'w-1/6', 'w-1/4', 'w-1/6'], 6)}</div>${skPagination()}`)}`;
}

function skCallersList() {
    return `
    <div class="flex items-center justify-between">
        ${skTitle('w-56')}
        <div class="flex gap-3">${skChip('w-32')}${skChip('w-32')}</div>
    </div>
    ${skCard(`${skChip('w-full')}<div class="mt-5 space-y-3">${Array.from({ length: 5 }, () =>
        `<div class="flex items-center gap-4 rounded-xl border border-gray-100 p-3">
            <div class="h-10 w-10 rounded-full bg-gray-100 animate-pulse"></div>
            <div class="flex-1 space-y-1">${skBar('w-32')}${skBar('w-40', 'h-2')}</div>
            ${skBar('w-20', 'h-6')}${skBar('w-24', 'h-8')}
        </div>`).join('')}</div>${skPagination()}`)}`;
}

function skCallSetup() {
    return `
    <div class="space-y-3">
        ${skTitle('w-80')}
        ${skBar('w-96', 'h-2')}
    </div>
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        ${skCard(`<div class="space-y-4">${skBar('w-40', 'h-3')}${skBar('w-16', 'h-2')}${skBar('w-full', 'h-11')}<div class="h-10 w-full rounded-lg bg-gray-100 animate-pulse"></div><div class="flex items-center gap-2">${skBar('w-8', 'h-2')}${skBar('w-full', 'h-1.5')}${skBar('w-8', 'h-2')}</div></div>`)}
        ${skCard(`<div class="space-y-4">${skBar('w-40', 'h-3')}${skBar('w-16', 'h-2')}${skBar('w-full', 'h-11')}<div class="h-10 w-full rounded-lg bg-gray-100 animate-pulse"></div><div class="flex items-center gap-2">${skBar('w-8', 'h-2')}${skBar('w-full', 'h-1.5')}${skBar('w-8', 'h-2')}</div></div>`)}
    </div>
    ${skCard(`<div class="flex flex-col sm:flex-row items-center justify-between gap-4">
        <div class="flex gap-3">${skBar('w-40', 'h-10')}${skBar('w-24', 'h-10')}</div>
        <div class="space-y-2">${skBar('w-24', 'h-2')}${skBar('w-20', 'h-7')}</div>
    </div>`)}`;
}

function skMasterHistory() {
    return `
    ${skTitle('w-72')}
    <div class="flex gap-3">${skChip('w-40')}${skChip('w-44')}${skChip('w-36')}</div>
    ${skCard(`${skTable(['w-1/6', 'w-1/4', 'w-1/5', 'w-1/6', 'w-1/6'], 7)}${skPagination()}`)}`;
}

function skHistory() {
    return `
    ${skTitle('w-64')}
    <div class="flex gap-3">${skChip('w-full')}${skChip('w-40')}${skChip('w-24')}</div>
    ${skCard(`${skTable(['w-1/5', 'w-1/4', 'w-1/5', 'w-1/6'], 7)}${skPagination()}`)}`;
}

function skReports() {
    return `
    <div class="flex items-center justify-between">
        ${skTitle('w-64')}
        <div class="flex gap-3">${skChip('w-32')}${skChip('w-36')}</div>
    </div>
    ${skCard(`${skTable(['w-1/3', 'w-1/5', 'w-1/6', 'w-1/4'], 6)}${skPagination()}`)}`;
}

function skDefault() {
    return `
    ${skTitle('w-64')}
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">${skStat()}${skStat()}${skStat()}${skStat()}</div>
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4 items-start">
        <div class="lg:col-span-2">${skCard(skTable(['w-1/4', 'w-1/4', 'w-1/4'], 6), 'min-h-[16rem]')}</div>
        ${skCard(`<div class="space-y-5">${skBar('w-32', 'h-4')}${skProgress()}${skProgress()}</div>`)}
    </div>`;
}

// Matched from longest to shortest prefix so '/schedules/admin-calendar/'
// never falls through to the responder calendar skeleton, etc.
// The third entry mirrors each page's max-width wrapper so the skeleton
// aligns exactly like the real content it stands in for.
const SKELETON_ROUTES = [
    ['/dashboard/admin', skAdminDashboard, 'max-w-6xl'],
    ['/dashboard', skResponderDashboard, 'max-w-6xl'],
    ['/forecast', skForecast, 'max-w-6xl'],
    ['/heatmap', skHeatmap, 'max-w-6xl'],
    ['/schedules/admin-calendar', skAdminCalendar, 'max-w-6xl'],
    ['/schedules', skResponderCalendar, 'max-w-6xl'],
    ['/accounts/manage', skAccountsManage, 'max-w-6xl'],
    ['/accounts/profile', skProfile, 'max-w-4xl'],
    ['/referrals/manage', skReferralsManage, 'max-w-6xl'],
    ['/referrals', skReferralsDirectory, 'max-w-5xl'],
    ['/callers/database', skCallersTable, 'max-w-6xl'],
    ['/callers/call-setup', skCallSetup, 'max-w-6xl'],
    ['/callers', skCallersList, 'max-w-6xl'],
    ['/documentation/master', skMasterHistory, 'max-w-6xl'],
    ['/documentation', skHistory, 'max-w-6xl'],
    ['/reports', skReports, 'max-w-6xl'],
];

function pickSkeletonRoute(pathname) {
    const path = pathname.endsWith('/') ? pathname : pathname + '/';
    for (const route of SKELETON_ROUTES) {
        const prefix = route[0].endsWith('/') ? route[0] : route[0] + '/';
        if (path === prefix || path.startsWith(prefix)) return route;
    }
    return [null, skDefault, 'max-w-6xl'];
}

function showSkeletonOverlay(url) {
    const container = document.getElementById('tab-content-container');
    if (!container || document.getElementById('page-skeleton-overlay')) return;

    let pathname = '/';
    try {
        pathname = new URL(url, window.location.href).pathname;
    } catch (err) { /* keep default */ }

    const [, builder, width] = pickSkeletonRoute(pathname);

    const overlay = document.createElement('div');
    overlay.id = 'page-skeleton-overlay';
    overlay.className = 'absolute inset-0 z-[1100] bg-bgLight overflow-y-auto custom-scrollbar';
    overlay.innerHTML = `<div class="p-4 sm:p-8 ${width} mx-auto w-full space-y-6">${builder()}</div>`;
    container.appendChild(overlay);
}

function hideSkeletonOverlay() {
    document.getElementById('page-skeleton-overlay')?.remove();
}

function isSkeletonNavigation(event) {
    const link = event.target.closest('a');
    if (!link || event.defaultPrevented) return false;
    // Only plain left-clicks navigate in this tab
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return false;
    const href = link.getAttribute('href');
    if (!href || href === '#') return false;
    if (/logout/i.test(href)) return false;
    if (link.hasAttribute('download')) return false;
    if (link.target && link.target !== '_self') return false;
    try {
        const url = new URL(href, window.location.href);
        if (url.origin !== window.location.origin) return false;
        // Same-page hash link: the browser scrolls, nothing is loading
        if (url.pathname === window.location.pathname &&
            url.search === window.location.search &&
            url.hash) return false;
    } catch (err) {
        return false;
    }
    return true;
}

// Capture phase so the skeleton shows even if other handlers stop propagation.
document.addEventListener('click', (event) => {
    if (isSkeletonNavigation(event)) showSkeletonOverlay(event.target.closest('a').getAttribute('href'));
}, true);

// Coming back via the back/forward cache restores the old page: drop any
// leftover skeleton so the restored content is visible.
window.addEventListener('pageshow', (event) => {
    if (event.persisted) hideSkeletonOverlay();
});


// =====================================================================
// --- Recording-safe navigation (keeps an active call alive) ---
//
// A normal navigation is a full page load, which tears down recorder.js and
// stops the active call. While a recording is in progress, internal links are
// fetched and swapped into #tab-content-container instead, so the recorder
// (and its MediaRecorder) keeps running across sections.
// =====================================================================

let ajaxNavigating = false;

// True while a call is recording, and also while a finished recording is
// still held in memory (so it can be reviewed/saved after stopping on another
// page). Full reloads would discard both, so those navigations are swapped.
function shouldPreserveCallState() {
    if (!window.CallRecorder) return false;
    if (typeof CallRecorder.isRecording === 'function' && CallRecorder.isRecording()) return true;
    return typeof CallRecorder.getLatestBlob === 'function' && !!CallRecorder.getLatestBlob();
}

function isAjaxNavigable(event) {
    const link = event.target.closest('a');
    if (!link || event.defaultPrevented) return false;
    // Only plain left-clicks navigate in this tab
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return false;
    const href = link.getAttribute('href');
    if (!href || href === '#') return false;
    if (link.hasAttribute('download')) return false;
    if (link.target && link.target !== '_self') return false;
    if (/logout/i.test(href)) return false;
    try {
        const url = new URL(href, window.location.href);
        if (url.origin !== window.location.origin) return false;
        // Same-page hash link: the browser scrolls, nothing is loading
        if (url.pathname === window.location.pathname &&
            url.search === window.location.search &&
            url.hash) return false;
    } catch (err) {
        return false;
    }
    return true;
}

function syncNavActive(pathname) {
    document.querySelectorAll('#main-sidebar .nav-btn').forEach(link => {
        let active = false;
        try {
            active = new URL(link.getAttribute('href'), window.location.href).pathname === pathname;
        } catch (err) {
            // Leave the link in its inactive state
        }
        link.classList.toggle('text-brand', active);
        link.classList.toggle('text-gray-400', !active);
        link.classList.toggle('hover:text-brand', !active);
        const icon = link.querySelector('i');
        if (icon) {
            icon.classList.toggle('ph-fill', active);
            icon.classList.toggle('ph', !active);
        }
    });
}

// Injected content has inert scripts; re-create each one so it runs, in order.
function runSwappedScripts(root) {
    const scripts = Array.from(root.querySelectorAll('script'));
    const originalAddEventListener = document.addEventListener;
    const domReady = document.readyState !== 'loading';

    // Scripts that wait for DOMContentLoaded would never run after a swap,
    // because the document has already finished loading. Run them right away.
    if (domReady) {
        document.addEventListener = function (type, fn, options) {
            if (type === 'DOMContentLoaded' && typeof fn === 'function') {
                setTimeout(() => {
                    try { fn.call(document, new Event('DOMContentLoaded')); }
                    catch (err) { console.error(err); }
                }, 0);
                return;
            }
            return originalAddEventListener.call(this, type, fn, options);
        };
    }

    let queue = Promise.resolve();
    scripts.forEach(oldScript => {
        // JSON data blocks and other non-JS scripts stay in place untouched.
        const type = oldScript.getAttribute('type');
        if (type && type !== 'text/javascript' && type !== 'module') return;

        const src = oldScript.getAttribute('src');
        queue = queue.then(() => {
            if (src) {
                const absolute = new URL(src, window.location.href).href;
                // Ignore the inert copies inside the swapped container; only a
                // script that was actually injected/loaded counts.
                const alreadyLoaded = Array.from(document.querySelectorAll('script[src]'))
                    .some(existing => existing.src === absolute && !root.contains(existing));
                if (alreadyLoaded) return;
                const fresh = document.createElement('script');
                Array.from(oldScript.attributes).forEach(attr => fresh.setAttribute(attr.name, attr.value));
                return new Promise(resolve => {
                    fresh.onload = resolve;
                    fresh.onerror = resolve;
                    document.head.appendChild(fresh);
                });
            }
            const fresh = document.createElement('script');
            Array.from(oldScript.attributes).forEach(attr => fresh.setAttribute(attr.name, attr.value));
            fresh.textContent = oldScript.textContent;
            oldScript.replaceWith(fresh);
        });
    });

    return queue.finally(() => {
        document.addEventListener = originalAddEventListener;
    });
}

async function ajaxNavigate(url, options) {
    if (!shouldPreserveCallState() || ajaxNavigating) return false;
    ajaxNavigating = true;
    showSkeletonOverlay(url);
    try {
        const response = await fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
        if (!response.ok) throw new Error('Request failed with status ' + response.status);
        const html = await response.text();
        const doc = new DOMParser().parseFromString(html, 'text/html');
        const next = doc.getElementById('tab-content-container');
        if (!next) throw new Error('Destination page has no tab content container');

        // Let the current page release timers/loops before it is detached.
        if (typeof window.beforePageSwap === 'function') {
            try { window.beforePageSwap(); } catch (err) { console.error(err); }
        }
        window.beforePageSwap = null;
        window.afterContentSwap = null;

        const container = document.getElementById('tab-content-container');
        if (!container) throw new Error('Tab content container is missing');
        container.innerHTML = next.innerHTML;
        container.scrollTop = 0;

        await runSwappedScripts(container);

        if (doc.title) document.title = doc.title;
        syncNavActive(new URL(url, window.location.href).pathname);

        if (!options || options.updateHistory !== false) {
            window.history.pushState({ sentiAjax: true }, '', url);
        }
        return true;
    } catch (err) {
        console.error('Recording-safe navigation failed:', err);
        window.location.href = url;
        return false;
    } finally {
        ajaxNavigating = false;
        hideSkeletonOverlay();
    }
}

document.addEventListener('click', (event) => {
    if (!shouldPreserveCallState() || !isAjaxNavigable(event)) return;
    const href = event.target.closest('a').getAttribute('href');
    event.preventDefault();
    ajaxNavigate(href);
});

// Back/forward while a call is held must swap content instead of reloading.
window.addEventListener('popstate', () => {
    if (!shouldPreserveCallState() || ajaxNavigating) return;
    ajaxNavigate(window.location.href, { updateHistory: false });
});

// Shared navigation helper for script-driven redirects (e.g. notification
// items) so they keep an active call alive instead of doing a full reload.
window.sentiNavigate = function (url) {
    if (shouldPreserveCallState()) {
        ajaxNavigate(url);
    } else {
        window.location.href = url;
    }
};

// Shared refresh helper: pages that used to call location.reload() can call
// this so refreshing does not discard an in-progress/unsaved call.
window.sentiRefresh = function () {
    if (shouldPreserveCallState()) {
        ajaxNavigate(window.location.href, { updateHistory: false });
    } else {
        window.location.reload();
    }
};

// A full reload or tab close would discard the call; ask before leaving.
window.addEventListener('beforeunload', (event) => {
    if (window.CallRecorder
        && typeof CallRecorder.isRecording === 'function'
        && CallRecorder.isRecording()) {
        event.preventDefault();
        event.returnValue = '';
    }
});


function populateLoginRole() {
    const roleSelect = document.getElementById('login-role');
    if (roleSelect) {
        roleSelect.value = getSelectedRole();
    }
}

// --- Notifications Toggle ---
function toggleNotifications() {
    const drop = document.getElementById('notification-dropdown');
    if(drop) drop.classList.toggle('hidden');
}

// --- Sidebar Toggle Logic ---
function toggleSidebar() {
    const sidebar = document.getElementById('main-sidebar');
    const backdrop = document.getElementById('sidebar-backdrop');
    if (!sidebar || !backdrop) return;
    if (window.innerWidth < 768) {
        const isHidden = sidebar.classList.contains('-translate-x-full');
        if (isHidden) {
            sidebar.classList.remove('-translate-x-full');
            sidebar.classList.add('translate-x-0', 'expanded');
            backdrop.classList.remove('hidden');
            sidebarOpen = true;
        } else {
            closeSidebar();
        }
    }
}

function closeSidebar() {
    const sidebar = document.getElementById('main-sidebar');
    const backdrop = document.getElementById('sidebar-backdrop');
    if (!sidebar || !backdrop) return;
    sidebar.classList.add('-translate-x-full');
    sidebar.classList.remove('translate-x-0', 'expanded');
    backdrop.classList.add('hidden');
    sidebarOpen = false;
}

// Close dropdowns when clicked outside
window.onclick = function(event) {
    if (!event.target.closest('#btn-notifications') && !event.target.closest('#notification-dropdown')) {
        const drop = document.getElementById('notification-dropdown');
        if (drop && !drop.classList.contains('hidden')) {
            drop.classList.add('hidden');
        }
    }
}

// Close mobile sidebar automatically when resizing up to desktop breakpoint
window.addEventListener('resize', function() {
    if (window.innerWidth >= 768 && sidebarOpen) closeSidebar();
});

// --- Generic Modals Logic ---
function openModal(id) {
    const backdrop = document.getElementById('modal-backdrop');
    const targetModal = document.getElementById(id);
    
    if (backdrop && targetModal) {
        backdrop.classList.remove('hidden');
        backdrop.classList.add('flex');
        document.querySelectorAll('.modal-content').forEach(el => el.classList.add('hidden'));
        targetModal.classList.remove('hidden');
    }
}

function closeModal() {
    const backdrop = document.getElementById('modal-backdrop');
    if (backdrop) {
        backdrop.classList.add('hidden');
        backdrop.classList.remove('flex');
    }
}

function submitModalAction(btn, successText) {
    const originalText = btn.innerText;
    btn.innerHTML = '<i class="ph-bold ph-spinner animate-spin"></i> Processing...';
    btn.classList.add('opacity-80', 'pointer-events-none');
    
    setTimeout(() => {
        btn.innerText = successText;
        btn.classList.replace('bg-brand', 'bg-blue-600');
        setTimeout(() => {
            closeModal();
            btn.innerText = originalText;
            btn.classList.replace('bg-blue-600', 'bg-brand');
            btn.classList.remove('opacity-80', 'pointer-events-none');
            
            // Specific logic to remove row if it was a leave approval
            if(btn.closest('#leave-row-1') || btn.closest('#leave-row-2')) {
                let row = btn.closest('tr') || btn.closest('.border'); 
                if (row) row.remove();
            }
        }, 1000);
    }, 800);
}

function approveLeave(rowId) {
    const row = document.getElementById(rowId);
    if(row) {
        if(row.tagName === 'TR') {
            row.innerHTML = `<td colspan="4" class="p-3 text-center text-xs font-bold text-gray-400">Request Processed</td>`;
        } else {
            row.innerHTML = `<div class="p-3 text-center text-xs font-bold text-gray-400">Request Processed</div>`;
        }
        setTimeout(() => { row.remove(); }, 1500);
    }
}

// --- Documentation Toggles Logic (Persistent Form Panel) ---
function toggleDocMode(mode) {
    const formPanel = document.getElementById('panel-doc-form');
    const manualPanel = document.getElementById('panel-doc-manual');
    const tabForm = document.getElementById('tab-doc-form');
    const tabManual = document.getElementById('tab-doc-manual');

    if(!formPanel || !manualPanel) return;

    if(mode === 'form') {
        formPanel.classList.remove('hidden');
        manualPanel.classList.add('hidden');
        
        tabForm.classList.add('text-brand', 'border-brand', 'border-b-2');
        tabForm.classList.remove('text-gray-400', 'hover:text-gray-600');
        
        tabManual.classList.remove('text-brand', 'border-brand', 'border-b-2');
        tabManual.classList.add('text-gray-400', 'hover:text-gray-600');
    } else {
        formPanel.classList.add('hidden');
        manualPanel.classList.remove('hidden');
        
        tabManual.classList.add('text-brand', 'border-brand', 'border-b-2');
        tabManual.classList.remove('text-gray-400', 'hover:text-gray-600');
        
        tabForm.classList.remove('text-brand', 'border-brand', 'border-b-2');
        tabForm.classList.add('text-gray-400', 'hover:text-gray-600');
    }
}

// --- Simulated AI Summarization Workflow (Auto-fill -> Summarize -> Save) ---
// function triggerAI() {
//     const btn = document.getElementById('ai-action-btn');
//     if (!btn) return;

//     if (aiStep === 0) {
//         btn.innerHTML = '<i class="ph-bold ph-spinner animate-spin text-xl"></i> AUTO-FILLING...';
//         btn.classList.add('opacity-80', 'pointer-events-none');

//         setTimeout(() => {
//             if(document.getElementById('aiName')) document.getElementById('aiName').value = 'Maria Santos';
//             if(document.getElementById('aiGender')) document.getElementById('aiGender').value = 'Female';
//             if(document.getElementById('aiStatus')) document.getElementById('aiStatus').value = 'Single';
//             if(document.getElementById('aiAge')) document.getElementById('aiAge').value = '22';
//             if(document.getElementById('aiLocation')) document.getElementById('aiLocation').value = 'Mandaue City';
//             if(document.getElementById('aiReason')) document.getElementById('aiReason').value = 'Relationship';
//             if(document.getElementById('aiRisk')) document.getElementById('aiRisk').value = 'Medium Risk';
//             if(document.getElementById('aiIntervention')) document.getElementById('aiIntervention').value = 'Active listening provided. Validated feelings regarding conflict with partner. Conducted standard risk assessment; no immediate plan but high emotional distress. Recommended breathing exercises.';
//             if(document.getElementById('aiComments')) document.getElementById('aiComments').value = 'Caller agreed to follow up with Bridget Olowojeje (PsychHub Co.) located in Cebu City. Texted clinic details to caller.';

//             btn.innerHTML = '<i class="ph-fill ph-sparkle text-xl group-hover:animate-pulse"></i> <span id="ai-btn-text">SUMMARIZE</span>';
//             btn.classList.remove('opacity-80', 'pointer-events-none');
//             aiStep = 1;
//         }, 1500);

//     } else if (aiStep === 1) {
//         btn.innerHTML = '<i class="ph-bold ph-spinner animate-spin text-xl"></i> SUMMARIZING...';
//         btn.classList.add('opacity-80', 'pointer-events-none');

//         setTimeout(() => {
//             const summaryContainer = document.getElementById('ai-summary-container');
//             const summaryText = document.getElementById('aiGeneratedSummary');
            
//             if(summaryContainer) summaryContainer.classList.remove('hidden');
//             if(summaryText) summaryText.value = 'AI Summary:\nCaller named Maria Santos (Female, 22, Single) from Mandaue City called due to relationship conflicts. Risk level assessed as Medium Risk. Active listening provided, validated feelings, and recommended breathing exercises. Caller agreed to follow up with PsychHub Co. in Cebu City.';

//             btn.innerHTML = '<i class="ph-fill ph-floppy-disk text-xl"></i> <span id="ai-btn-text">SAVE RECORD</span>';
//             btn.classList.remove('opacity-80', 'pointer-events-none');
//             aiStep = 2;
//         }, 1500);

//     } else if (aiStep === 2) {
//         btn.innerHTML = '<i class="ph-bold ph-spinner animate-spin text-xl"></i> SAVING...';
//         btn.classList.add('opacity-80', 'pointer-events-none');

//         setTimeout(() => {
//             btn.innerHTML = '<i class="ph-fill ph-check-circle text-xl"></i> APPROVED & SAVED';
//             btn.classList.remove('bg-brand');
//             btn.classList.add('bg-blue-600');
            
//             setTimeout(() => {
//                 btn.innerHTML = '<i class="ph-fill ph-sparkle text-xl group-hover:animate-pulse"></i> <span id="ai-btn-text">SUMMARIZE</span>';
//                 btn.classList.add('bg-brand');
//                 btn.classList.remove('bg-blue-600', 'opacity-80', 'pointer-events-none');
//                 aiStep = 0;
//             }, 2000);
//         }, 1000);
//     }
// }

// --- Chart.js Initialization ---
// Reads server-provided values from the canvas' data-values attribute,
// falling back to the seeded design values when none were injected.
function chartValues(canvas, fallback) {
    if (!canvas) return fallback;
    const raw = canvas.getAttribute('data-values');
    if (!raw) return fallback;
    try {
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) && parsed.length ? parsed : fallback;
    } catch (err) {
        return fallback;
    }
}

function initCharts() {
    if (typeof Chart === 'undefined') return;

    chartsInstance.forEach(c => c.destroy());
    chartsInstance = [];

    Chart.defaults.font.family = 'Inter';
    Chart.defaults.color = '#94a3b8';
    Chart.defaults.scale.grid.color = '#f1f5f9';

    // RESPONDER CHARTS
    const ctxReasons = document.getElementById('chartReasons');
    if (ctxReasons && ctxReasons.offsetParent !== null) {
        chartsInstance.push(new Chart(ctxReasons.getContext('2d'), {
            type: 'doughnut',
            data: {
                labels: ['Relationships', 'Suicidal Crisis', 'Career', 'Others'],
                datasets: [{
                    data: chartValues(ctxReasons, [25, 25, 25, 25]),
                    backgroundColor: ['#00a67e', '#fbbf24', '#34d399', '#047857'],
                    borderWidth: 0,
                    cutout: '75%',
                    borderRadius: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false }, tooltip: { enabled: false } },
                animation: { animateScale: true }
            }
        }));
    }

    const ctxCallers = document.getElementById('chartCallers');
    if (ctxCallers && ctxCallers.offsetParent !== null) {
        chartsInstance.push(new Chart(ctxCallers.getContext('2d'), {
            type: 'doughnut',
            data: {
                labels: ['Men', 'Women', 'LGBTQIA'],
                datasets: [
                    { 
                        data: chartValues(ctxCallers, [25, 70, 5]),
                        backgroundColor: ['#00a67e', '#34d399', '#a7f3d0'],
                        borderWidth: 2,
                        borderColor: '#ffffff',
                        cutout: '80%',
                        borderRadius: 10
                    },
                    { 
                        data: [100],
                        backgroundColor: ['transparent'],
                        borderWidth: 2,
                        borderColor: '#00a67e',
                        cutout: '70%',
                        radius: '85%'
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false }, tooltip: { enabled: false } },
                layout: { padding: 10 }
            }
        }));
    }

    const ctxSuicide = document.getElementById('chartSuicide');
    if (ctxSuicide && ctxSuicide.offsetParent !== null) {
        chartsInstance.push(new Chart(ctxSuicide.getContext('2d'), {
            type: 'doughnut',
            data: {
                labels: ['High Risk', 'Low/No Risk'],
                datasets: [{
                    data: chartValues(ctxSuicide, [32, 68]),
                    backgroundColor: ['#00a67e', '#e2e8f0'],
                    borderWidth: 0,
                    cutout: '80%',
                    borderRadius: 5
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                rotation: 270, 
                circumference: 180, 
                plugins: { legend: { display: false }, tooltip: { enabled: false } }
            }
        }));
    }

    const ctxVolume = document.getElementById('chartVolume');
    if (ctxVolume && ctxVolume.offsetParent !== null) {
        const gradient = ctxVolume.getContext('2d').createLinearGradient(0, 0, 0, 150);
        gradient.addColorStop(0, '#34d399');
        gradient.addColorStop(1, '#a7f3d0');

        chartsInstance.push(new Chart(ctxVolume.getContext('2d'), {
            type: 'bar',
            data: {
                labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'June', 'July', 'Aug', 'Sept', 'Oct', 'Nov', 'Dec'],
                datasets: [{
                    data: chartValues(ctxVolume, [45, 60, 75, 75, 50, 40, 50, 65, 85, 15, 5, 5]),
                    backgroundColor: gradient,
                    borderRadius: 10,
                    borderSkipped: false,
                    barThickness: 10
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { 
                        grid: { display: false },
                        ticks: { font: { size: 10, weight: 'bold' }, color: '#475569' },
                        border: { display: false }
                    },
                    y: { display: false }
                }
            }
        }));
    }
    
    // ADMIN CHARTS
    const ctxAdminForecast = document.getElementById('chartAdminForecast');
    if (ctxAdminForecast && ctxAdminForecast.offsetParent !== null) {
        const attrArray = (name, fallback) => {
            const raw = ctxAdminForecast.getAttribute(name);
            if (!raw) return fallback;
            try {
                const parsed = JSON.parse(raw);
                return Array.isArray(parsed) && parsed.length ? parsed : fallback;
            } catch (err) {
                return fallback;
            }
        };
        const labels = attrArray('data-labels', ['Month 1', 'Month 2', 'Month 3']);
        const total = attrArray('data-values', [0, 0, 0]);
        const lower = attrArray('data-lower', total);
        const upper = attrArray('data-upper', total);

        chartsInstance.push(new Chart(ctxAdminForecast.getContext('2d'), {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Expected total calls',
                        data: total,
                        borderColor: '#00a67e',
                        backgroundColor: '#00a67e',
                        tension: 0.35,
                        borderWidth: 3,
                        pointRadius: 3,
                        pointBackgroundColor: '#00a67e'
                    },
                    {
                        label: 'Estimated range (lower)',
                        data: lower,
                        borderColor: 'transparent',
                        pointRadius: 0,
                        fill: false
                    },
                    {
                        label: 'Estimated range',
                        data: upper,
                        borderColor: 'transparent',
                        backgroundColor: 'rgba(0, 166, 126, 0.15)',
                        pointRadius: 0,
                        fill: '-1'
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            usePointStyle: true,
                            boxWidth: 6,
                            filter: (item) => item.text !== 'Estimated range (lower)'
                        }
                    },
                    tooltip: {
                        callbacks: {
                            title: (items) => items.length ? items[0].label : '',
                            label: (item) => {
                                const value = item.parsed.y;
                                if (value === null || value === undefined) return '';
                                const lowerValue = lower[item.dataIndex];
                                const upperValue = upper[item.dataIndex];
                                if (item.dataset.label === 'Estimated range (lower)') return '';
                                if (item.dataset.label === 'Estimated range') {
                                    if (lowerValue === null || lowerValue === undefined) return '';
                                    return `Estimated range: ${Math.round(lowerValue).toLocaleString()}–${Math.round(upperValue).toLocaleString()} calls`;
                                }
                                return `${Math.round(value).toLocaleString()} calls`;
                            },
                            afterBody: (items) => {
                                const first = items[0];
                                if (!first) return '';
                                const lowerValue = lower[first.dataIndex];
                                const upperValue = upper[first.dataIndex];
                                if (lowerValue === null || lowerValue === undefined) return '';
                                return 'Actual call volume may fall outside this estimated range.';
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: { borderDash: [4, 4] },
                        title: { display: true, text: 'Expected calls' }
                    },
                    x: { grid: { display: false } }
                }
            }
        }));
    }
}


// =====================================================================
// --- Forecast Generation (Call Volume Forecast page) ---
//
// The page posts the form normally: the server generates the run, publishes
// it and redirects back to the Call Volume Forecast page with the result.
// This handler only adds the loading state.
//
// The listeners are delegated on `document` on purpose: a listener bound to
// the form element itself would be lost if the page content is ever swapped
// out dynamically, and delegation keeps working in that case.
// =====================================================================

let forecastGenerationBound = false;

function initForecastGeneration() {
    if (forecastGenerationBound) return;
    forecastGenerationBound = true;

    document.addEventListener('submit', function(event) {
        const form = event.target;
        if (!form || form.id !== 'forecast-generate-form') return;

        // Ignore repeat submissions while one is already on its way.
        if (window.__forecastGenerationSubmitting) {
            event.preventDefault();
            return;
        }
        window.__forecastGenerationSubmitting = true;

        const button = form.querySelector('#forecast-generate-button');
        const label = form.querySelector('#forecast-generate-label');
        // The button is only styled, never disabled: a disabled control is
        // left out of the posted form data, and the server needs the
        // button's action marker to tell an explicit click apart from an
        // implicit submission.
        if (button) {
            button.classList.add('opacity-60', 'cursor-not-allowed');
            button.setAttribute('aria-busy', 'true');
        }
        if (label) label.textContent = 'Generating…';
    });

    document.addEventListener('keydown', function(event) {
        if (event.key !== 'Enter') return;
        const target = event.target;
        // Enter in the horizon selector must never submit the form.
        if (target && target.id === 'forecast-horizon') {
            event.preventDefault();
        }
    });

    // A page restored from the back/forward cache must be able to submit again.
    window.addEventListener('pageshow', function() {
        window.__forecastGenerationSubmitting = false;
    });
}


// =====================================================================
// --- Manage Users (Responder) Logic ---
// =====================================================================

function openResponderModal(id) {
    const el = document.getElementById(id);
    if (el) {
        el.classList.remove('hidden');
        el.classList.add('flex');
    }
}

function closeResponderModal(id) {
    const el = document.getElementById(id);
    if (el) {
        el.classList.add('hidden');
        el.classList.remove('flex');
    }
}

const userImageInput = document.getElementById('user_image');
if (userImageInput) {
    userImageInput.addEventListener('change', function(e) {
        const file = e.target.files[0];
        if (file) {
            const reader = new FileReader();
            reader.onload = (event) => {
                const preview = document.getElementById('image-preview');
                const placeholder = document.getElementById('image-placeholder');
                preview.src = event.target.result;
                preview.classList.remove('hidden');
                placeholder.classList.add('hidden');
            };
            reader.readAsDataURL(file);
        }
    });
}


function resetResponderForm() {
    const form = document.getElementById('responder-form');
    if (!form) return;
    form.reset();
    document.getElementById('profile_id').value = '';
    document.getElementById('status-field').classList.add('hidden');
    document.getElementById('modal-title').textContent = 'Add Responder';
    document.getElementById('submit-btn').textContent = 'Save Responder';
    
    // Reset Image Preview
    const preview = document.getElementById('image-preview');
    const placeholder = document.getElementById('image-placeholder');
    if (preview) {
        preview.src = '';
        preview.classList.add('hidden');
    }
    if (placeholder) {
        placeholder.classList.remove('hidden');
    }
}


function openAddResponderModal() {
    const form = document.getElementById('add-responder-form');
    if (form) form.reset();
    openModal('modal-add-responder');
}

function openViewResponderModal(profileId) {
    fetch(`/accounts/accounts/${profileId}/`, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
    .then(r => r.json())
    .then(data => {
        if (!data.success) return CenterAlert.fire({ icon: 'error', title: 'Failed to load responder.' });
        const p = data.profile;
        const fullName = [p.first_name, p.last_name].filter(Boolean).join(' ') || p.email;
        document.getElementById('vr-name').textContent = fullName;
        document.getElementById('vr-role').textContent = p.user_role || 'Responder';
        document.getElementById('vr-email').textContent = p.email;
        document.getElementById('vr-number').textContent = p.user_number || '—';
        document.getElementById('vr-location').textContent = p.user_location || '—';
        const isActive = (p.user_status || '').toLowerCase() === 'active';
        document.getElementById('vr-status').innerHTML = isActive
            ? '<span class="px-2 py-1 bg-green-100 text-green-700 text-[10px] rounded-full font-bold">Active</span>'
            : '<span class="px-2 py-1 bg-red-100 text-red-700 text-[10px] rounded-full font-bold">Inactive</span>';
        const img = document.getElementById('vr-image');
        const ph = document.getElementById('vr-image-placeholder');
        if (p.user_image) {
            const preloader = new Image();
            preloader.onload = () => { img.src = p.user_image; img.classList.remove('hidden'); ph.classList.add('hidden'); };
            preloader.onerror = () => { img.classList.add('hidden'); ph.classList.remove('hidden'); };
            preloader.src = p.user_image;
        } else {
            img.src = ''; img.classList.add('hidden'); ph.classList.remove('hidden');
        }
        openModal('modal-view-responder');
    })
    .catch(() => CenterAlert.fire({ icon: 'error', title: 'An error occurred while loading the responder.' }));
}

function setToggle(group, value) {
    const buttons = document.querySelectorAll(`[data-toggle="${group}"]`);
    buttons.forEach((btn) => {
        const active = btn.dataset.value === value;
        const checkIcon = btn.querySelector('.ph-check-circle-fill');

        const baseClass = "toggle-card w-full flex items-center gap-3 p-3 border-2 rounded-xl transition-all text-left";
        
        if (active) {
            if (group === 'user_status') {
                if (value === 'Active') {
                    btn.className = `${baseClass} border-green-500 bg-green-50 text-green-700 shadow-sm`;
                } else {
                    btn.className = `${baseClass} border-red-400 bg-red-50 text-red-600 shadow-sm`;
                }
            } else {
                btn.className = `${baseClass} border-brand bg-brand-light text-brand-dark shadow-sm`;
            }
            if (checkIcon) checkIcon.classList.remove('hidden');
        } else {
            btn.className = `${baseClass} border-gray-200 bg-white text-gray-500 hover:border-gray-300`;
            if (checkIcon) checkIcon.classList.add('hidden');
        }
    });
    document.getElementById(group).value = value;
}

function openEditResponderModal(profileId) {
    fetch(`/accounts/accounts/${profileId}/`, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
    .then(r => r.json())
    .then(data => {
        if (!data.success) return CenterAlert.fire({ icon: 'error', title: 'Failed to load responder.' });
        const p = data.profile;
        document.getElementById('profile_id').value = p.profile_id;
        setToggle('user_status', p.user_status || 'Active');
        setToggle('user_role', p.user_role || 'Responder');
        openModal('modal-add-edit-responder');
    })
    .catch(() => CenterAlert.fire({ icon: 'error', title: 'An error occurred while loading the responder.' }));
}

function copyGeneratedPassword(event) {
    const pwd = document.getElementById('gp-password').textContent;
    const btn = event.currentTarget;
    const icon = btn.querySelector('i');
    const original = icon.className;

    function onSuccess() {
        icon.className = 'ph-bold ph-check text-lg text-green-600';
        const label = document.getElementById('copy-label');
        if (label) { label.textContent = 'Copied!'; }
        setTimeout(() => {
            icon.className = original;
            if (label) { label.textContent = 'Copy'; }
        }, 1500);
    }

    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(pwd).then(onSuccess).catch(fallback);
    } else {
        fallback();
    }

    function fallback() {
        const ta = document.createElement('textarea');
        ta.value = pwd;
        ta.style.cssText = 'position:fixed;opacity:0;pointer-events:none';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        try {
            document.execCommand('copy');
            onSuccess();
        } catch {
            CenterAlert.fire({ icon: 'error', title: 'Failed to copy. Please copy manually.' });
        }
        document.body.removeChild(ta);
    }
}


// Render charts and attach form listeners globally if elements exist on page load
document.addEventListener("DOMContentLoaded", function() {
    try {
        initCharts();
    } catch (err) {
        console.error('initCharts failed:', err);
    }

    try {
        initForecastGeneration();
    } catch (err) {
        console.error('initForecastGeneration failed:', err);
    }

    document.addEventListener('mouseover', function(e) {
        const sidebar = e.target.closest('#main-sidebar');
        if (sidebar && window.innerWidth >= 768 && !sidebar.classList.contains('expanded')) {
            sidebar.classList.add('expanded');
            document.getElementById('sidebar-brand-name')?.classList.remove('hidden');
        }
    });
    document.addEventListener('mouseout', function(e) {
        const sidebar = e.target.closest('#main-sidebar');
        const toEl = e.relatedTarget;
        if (sidebar && (!toEl || !sidebar.contains(toEl)) && window.innerWidth >= 768) {
            sidebar.classList.remove('expanded');
            document.getElementById('sidebar-brand-name')?.classList.add('hidden');
        }
    });

    document.querySelectorAll('.toggle-card').forEach(btn => {
        btn.addEventListener('click', () => setToggle(btn.dataset.toggle, btn.dataset.value));
    });

    const addResponderForm = document.getElementById('add-responder-form');
    if (addResponderForm) {
        addResponderForm.addEventListener('submit', function (e) {
            e.preventDefault();
            const formData = new FormData(this);
            fetch('/accounts/accounts/add/', {
                method: 'POST',
                body: formData,
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
            })
            .then(r => {
                return r.json().then(data => {
                    if (!r.ok) throw new Error(data.message || `Request failed with status ${r.status}.`);
                    return data;
                });
            })
            .then(data => {
                if (!data.success) {
                    CenterAlert.fire({ 
                        icon: 'error', 
                        title: data.message || 'Something went wrong.'
                    });
                    return;
                }
                  
                closeModal();
      
                CenterAlert.fire({
                    icon: 'success',
                    title: 'Invitation Sent!',
                    text: data.message
                }).then(() => {
                    location.reload(); 
                });
            })
            .catch(err => {
                console.error(err);
                CenterAlert.fire({ 
                    icon: 'error', 
                    title: err.message || 'An unexpected error occurred.'
                });
            });
        });
    }

    const responderForm = document.getElementById('responder-form');
    if (responderForm) {
        responderForm.addEventListener('submit', function (e) {
            e.preventDefault();
            const profileId = document.getElementById('profile_id').value;
            const url = profileId ? `/accounts/accounts/${profileId}/edit/` : '/accounts/accounts/add/';
            const formData = new FormData(this);

            fetch(url, {
                method: 'POST',
                body: formData,
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
            })
            .then(r => {
                if (!r.ok) return r.text().then(t => { throw new Error(`HTTP ${r.status}: ${t.substring(0, 300)}`); });
                return r.json();
            })
            .then(data => {
                if (!data.success) {
                    CenterAlert.fire({ icon: 'error', title: data.message || 'Something went wrong.' });
                    return;
                }

                if (profileId) {
                    closeModal();
                    CenterAlert.fire({ icon: 'success', title: 'Updated!', text: data.message, timer: 2000 })
                        .then(() => location.reload());
                } else {
                    closeModal();
                    CenterAlert.fire({
                        icon: 'success',
                        title: 'Invitation Sent!',
                        text: data.message
                    }).then(() => {
                        location.reload();
                    });
                }
            })
            .catch(err => { 
                console.error('Responder form error:', err); 
                CenterAlert.fire({ icon: 'error', title: err.message }); 
            });
        });

        const responderSearch = document.getElementById('responder-search');
        if (responderSearch) {
            let debounceTimer;
            responderSearch.addEventListener('input', function () {
                clearTimeout(debounceTimer);
                debounceTimer = setTimeout(() => this.form.submit(), 400);
            });
            responderSearch.addEventListener('search', function () {
                if (!this.value) this.form.submit();
            });
        }
    }
});
