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
        window.location.href = '/dashboard/admin/';
    } else {
        window.location.href = '/dashboard/';
    }
}

function handleLogin() {
    const roleSelect = document.getElementById('login-role');
    const role = roleSelect ? roleSelect.value : 'responder';
    applySelectedRole(role);
    window.location.href = role === 'admin' ? '/dashboard/admin/' : '/dashboard/';
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
function triggerAI() {
    const btn = document.getElementById('ai-action-btn');
    if (!btn) return;

    if (aiStep === 0) {
        btn.innerHTML = '<i class="ph-bold ph-spinner animate-spin text-xl"></i> AUTO-FILLING...';
        btn.classList.add('opacity-80', 'pointer-events-none');

        setTimeout(() => {
            if(document.getElementById('aiName')) document.getElementById('aiName').value = 'Maria Santos';
            if(document.getElementById('aiGender')) document.getElementById('aiGender').value = 'Female';
            if(document.getElementById('aiStatus')) document.getElementById('aiStatus').value = 'Single';
            if(document.getElementById('aiAge')) document.getElementById('aiAge').value = '22';
            if(document.getElementById('aiLocation')) document.getElementById('aiLocation').value = 'Mandaue City';
            if(document.getElementById('aiReason')) document.getElementById('aiReason').value = 'Relationship';
            if(document.getElementById('aiRisk')) document.getElementById('aiRisk').value = 'Medium Risk';
            if(document.getElementById('aiIntervention')) document.getElementById('aiIntervention').value = 'Active listening provided. Validated feelings regarding conflict with partner. Conducted standard risk assessment; no immediate plan but high emotional distress. Recommended breathing exercises.';
            if(document.getElementById('aiComments')) document.getElementById('aiComments').value = 'Caller agreed to follow up with Bridget Olowojeje (PsychHub Co.) located in Cebu City. Texted clinic details to caller.';

            btn.innerHTML = '<i class="ph-fill ph-sparkle text-xl group-hover:animate-pulse"></i> <span id="ai-btn-text">SUMMARIZE</span>';
            btn.classList.remove('opacity-80', 'pointer-events-none');
            aiStep = 1;
        }, 1500);

    } else if (aiStep === 1) {
        btn.innerHTML = '<i class="ph-bold ph-spinner animate-spin text-xl"></i> SUMMARIZING...';
        btn.classList.add('opacity-80', 'pointer-events-none');

        setTimeout(() => {
            const summaryContainer = document.getElementById('ai-summary-container');
            const summaryText = document.getElementById('aiGeneratedSummary');
            
            if(summaryContainer) summaryContainer.classList.remove('hidden');
            if(summaryText) summaryText.value = 'AI Summary:\nCaller named Maria Santos (Female, 22, Single) from Mandaue City called due to relationship conflicts. Risk level assessed as Medium Risk. Active listening provided, validated feelings, and recommended breathing exercises. Caller agreed to follow up with PsychHub Co. in Cebu City.';

            btn.innerHTML = '<i class="ph-fill ph-floppy-disk text-xl"></i> <span id="ai-btn-text">SAVE RECORD</span>';
            btn.classList.remove('opacity-80', 'pointer-events-none');
            aiStep = 2;
        }, 1500);

    } else if (aiStep === 2) {
        btn.innerHTML = '<i class="ph-bold ph-spinner animate-spin text-xl"></i> SAVING...';
        btn.classList.add('opacity-80', 'pointer-events-none');

        setTimeout(() => {
            btn.innerHTML = '<i class="ph-fill ph-check-circle text-xl"></i> APPROVED & SAVED';
            btn.classList.remove('bg-brand');
            btn.classList.add('bg-blue-600');
            
            setTimeout(() => {
                btn.innerHTML = '<i class="ph-fill ph-sparkle text-xl group-hover:animate-pulse"></i> <span id="ai-btn-text">SUMMARIZE</span>';
                btn.classList.add('bg-brand');
                btn.classList.remove('bg-blue-600', 'opacity-80', 'pointer-events-none');
                aiStep = 0;
            }, 2000);
        }, 1000);
    }
}

// --- Chart.js Initialization ---
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
                    data: [25, 25, 25, 25],
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
                        data: [25, 70, 5],
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
                    data: [32, 68],
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
                    data: [45, 60, 75, 75, 50, 40, 50, 65, 85, 15, 5, 5],
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
        chartsInstance.push(new Chart(ctxAdminForecast.getContext('2d'), {
            type: 'line',
            data: {
                labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri (Forecast)', 'Sat (Forecast)', 'Sun (Forecast)'],
                datasets: [
                    {
                        label: 'Historical Actuals',
                        data: [112, 125, 118, 140, null, null, null],
                        borderColor: '#94a3b8',
                        backgroundColor: '#94a3b8',
                        tension: 0.4,
                        borderWidth: 2
                    },
                    {
                        label: 'AI Prediction Surge',
                        data: [null, null, null, 140, 245, 190, 160],
                        borderColor: '#ef4444',
                        backgroundColor: '#ef4444',
                        borderDash: [5, 5],
                        tension: 0.4,
                        borderWidth: 3,
                        pointRadius: 4,
                        pointBackgroundColor: '#ef4444'
                    }
                ]
            },
            options: { 
                responsive: true, 
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'bottom', labels: { usePointStyle: true, boxWidth: 6 } }
                },
                scales: {
                    y: { beginAtZero: true, grid: { borderDash: [4, 4] } },
                    x: { grid: { display: false } }
                }
            }
        }));
    }
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