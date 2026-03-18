/* ==========================================================================
   ROC Case Management — Main JavaScript
   ========================================================================== */

(function () {
    'use strict';

    /* ── Theme ──────────────────────────────────────────────────────────── */
    const isLoginPage = document.body.classList.contains('lt-login-body');

    function getStoredTheme() {
        return localStorage.getItem('lt-theme') || 'light';
    }

    function setTheme(theme) {
        if (isLoginPage) {
            document.documentElement.removeAttribute('data-bs-theme');
            return;
        }
        document.documentElement.setAttribute('data-bs-theme', theme);
        localStorage.setItem('lt-theme', theme);
        const icon = document.getElementById('themeIcon');
        if (icon) {
            icon.className = theme === 'dark' ? 'bi bi-sun-fill' : 'bi bi-moon-fill';
        }
    }

    // Apply immediately
    if (!isLoginPage) {
        setTheme(getStoredTheme());
    }

    document.addEventListener('DOMContentLoaded', function () {

        /* ── Global CSRF Token Setup (SEC-2) ────────────────────────────── */
        var csrfToken = document.querySelector('meta[name=csrf-token]')?.content || '';

        // Patch fetch to include CSRF token for mutating requests
        var originalFetch = window.fetch;
        window.fetch = function(url, options) {
            options = options || {};
            var method = (options.method || 'GET').toUpperCase();
            if (['POST', 'PUT', 'DELETE', 'PATCH'].includes(method)) {
                options.headers = options.headers || {};
                if (options.headers instanceof Headers) {
                    if (!options.headers.has('X-CSRFToken')) {
                        options.headers.set('X-CSRFToken', csrfToken);
                    }
                } else {
                    if (!options.headers['X-CSRFToken']) {
                        options.headers['X-CSRFToken'] = csrfToken;
                    }
                }
            }
            return originalFetch.call(this, url, options);
        };

        // Also set up jQuery AJAX CSRF headers if jQuery is available
        if (typeof $ !== 'undefined' && $.ajaxSetup) {
            $.ajaxSetup({
                beforeSend: function(xhr, settings) {
                    if (!/^(GET|HEAD|OPTIONS|TRACE)$/i.test(settings.type) && !this.crossDomain) {
                        xhr.setRequestHeader('X-CSRFToken', csrfToken);
                    }
                }
            });
        }

        /* ── Theme Toggle ───────────────────────────────────────────────── */
        const themeToggle = document.getElementById('themeToggle');
        if (themeToggle) {
            themeToggle.addEventListener('click', function () {
                const newTheme = getStoredTheme() === 'dark' ? 'light' : 'dark';
                setTheme(newTheme);
            });
        }

        /* ── Sidebar Collapse (Desktop) ─────────────────────────────────── */
        const sidebar = document.getElementById('ltSidebar');
        const collapseBtn = document.getElementById('sidebarCollapseBtn');

        function getSidebarState() {
            return localStorage.getItem('lt-sidebar-collapsed') === 'true';
        }

        function syncCollapsedSidebarTooltips() {
            if (!sidebar) return;
            const isCollapsed = sidebar.classList.contains('collapsed');
            sidebar.querySelectorAll('.lt-sidebar-link').forEach(function (link) {
                const label = link.getAttribute('data-tooltip') ||
                              (link.querySelector('span') ? link.querySelector('span').textContent.trim() : '');
                if (!label) return;
                if (isCollapsed) {
                    link.setAttribute('title', label);
                } else {
                    link.removeAttribute('title');
                }
            });
        }

        /* Highlight active quick-range button */
        function highlightActiveQuickRangeButton() {
            const searchParams = new URLSearchParams(window.location.search);
            const activeRange = searchParams.get('range');
            
            if (activeRange) {
                const buttons = document.querySelectorAll('.btn-quick-range');
                buttons.forEach(function (btn) {
                    if (btn.getAttribute('data-range') === activeRange) {
                        btn.classList.add('active');
                    } else {
                        btn.classList.remove('active');
                    }
                });
            }
        }
        highlightActiveQuickRangeButton();

        if (sidebar && getSidebarState()) {
            sidebar.classList.add('collapsed');
        }
        syncCollapsedSidebarTooltips();

        if (collapseBtn && sidebar) {
            collapseBtn.addEventListener('click', function () {
                sidebar.classList.toggle('collapsed');
                localStorage.setItem('lt-sidebar-collapsed',
                    sidebar.classList.contains('collapsed'));
                syncCollapsedSidebarTooltips();
            });
        }

        /* ── Sidebar Mobile Toggle ──────────────────────────────────────── */
        const mobileToggle = document.getElementById('mobileMenuBtn');
        const overlay = document.getElementById('sidebarOverlay');

        function openMobileSidebar() {
            if (sidebar) sidebar.classList.add('mobile-open');
            if (overlay) overlay.classList.add('show');
        }
        function closeMobileSidebar() {
            if (sidebar) sidebar.classList.remove('mobile-open');
            if (overlay) overlay.classList.remove('show');
        }

        if (mobileToggle) mobileToggle.addEventListener('click', openMobileSidebar);
        if (overlay) overlay.addEventListener('click', closeMobileSidebar);

        /* ── Notification Polling ────────────────────────────────────────── */
        const notifBadge = document.getElementById('notifBadge');
        const notifList = document.getElementById('notifList');
        const POLL_INTERVAL = 30000;

        function pollNotifications() {
            fetch('/api/notifications/count')
                .then(r => r.json())
                .then(data => {
                    if (notifBadge) {
                        if (data.count > 0) {
                            notifBadge.textContent = data.count > 99 ? '99+' : data.count;
                            notifBadge.style.display = '';
                        } else {
                            notifBadge.style.display = 'none';
                        }
                    }
                })
                .catch(() => {});
        }

        // BUG-10: Fetch and render notification list into dropdown
        function fetchNotificationList() {
            if (!notifList) return;
            fetch('/api/notifications')
                .then(r => r.json())
                .then(notifications => {
                    if (!notifications.length) {
                        notifList.innerHTML = '<p class="text-muted text-center small py-3">No notifications</p>';
                        return;
                    }
                    var html = '';
                    notifications.forEach(function(n) {
                        var readClass = n.is_read ? 'lt-notif-read' : 'fw-semibold';
                        var unreadClass = n.is_read ? '' : ' lt-notif-unread';
                        var icon = n.type === 'assignment' ? 'bi-person-plus' :
                                   n.type === 'deadline' ? 'bi-clock' :
                                   n.type === 'comment' ? 'bi-chat' :
                                   n.type === 'status_change' ? 'bi-arrow-repeat' :
                                   n.type === 'import' ? 'bi-cloud-upload' : 'bi-bell';
                        var timeStr = n.created_at ? window.timeAgo(n.created_at) : '';
                        var href = n.letter_id ? '/letter/' + n.letter_id : '#';
                        html += '<a class="dropdown-item d-flex align-items-start gap-2 py-2 px-3 ' + readClass + unreadClass + '" ' +
                                'href="' + href + '" data-notif-id="' + n.id + '">' +
                                '<i class="bi ' + icon + ' mt-1"></i>' +
                                '<div class="flex-grow-1">' +
                                '<div class="small text-wrap">' + (n.message || '') + '</div>' +
                                '<small class="lt-notif-time">' + timeStr + '</small>' +
                                '</div></a>';
                    });
                    notifList.innerHTML = html;
                })
                .catch(function() {
                    notifList.innerHTML = '<p class="text-muted text-center small py-2">Failed to load</p>';
                });
        }

        // Mark individual notification as read on click
        document.addEventListener('click', function(e) {
            var notifItem = e.target.closest('[data-notif-id]');
            if (!notifItem) return;
            var nid = notifItem.getAttribute('data-notif-id');
            if (nid) {
                fetch('/api/notifications/mark-read/' + nid, { method: 'POST' }).catch(function(){});
            }
        });

        // Mark all notifications read via AJAX
        var markAllBtn = document.getElementById('markAllReadBtn');
        if (markAllBtn) {
            markAllBtn.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                fetch('/api/notifications/mark-all-read', { method: 'POST' })
                    .then(function(r) { return r.json(); })
                    .then(function() {
                        if (notifBadge) notifBadge.style.display = 'none';
                        // Refresh notification list
                        fetchNotificationList();
                        window.ltToast('All notifications marked as read', 'success');
                    })
                    .catch(function() {
                        window.ltToast('Failed to mark notifications', 'danger');
                    });
            });
        }

        // Load notification list when dropdown opens
        var notifDropdown = document.getElementById('notifDropdown');
        if (notifDropdown) {
            var bellBtn = document.getElementById('notificationBell');
            if (bellBtn) {
                bellBtn.addEventListener('click', function() {
                    fetchNotificationList();
                });
            }
        }

        if (!isLoginPage) {
            pollNotifications();
            setInterval(pollNotifications, POLL_INTERVAL);
        }

        /* ── Toast System ───────────────────────────────────────────────── */
        window.ltToast = function (message, type) {
            type = type || 'info';
            const container = document.getElementById('toastContainer');
            if (!container) return;

            const icons = {
                success: 'bi-check-circle-fill',
                danger: 'bi-exclamation-circle-fill',
                warning: 'bi-exclamation-triangle-fill',
                info: 'bi-info-circle-fill'
            };

            const toast = document.createElement('div');
            toast.className = 'lt-toast lt-toast-' + type;
            toast.innerHTML =
                '<i class="lt-toast-icon bi ' + (icons[type] || icons.info) + '"></i>' +
                '<span class="lt-toast-message">' + message + '</span>' +
                '<button class="btn-close btn-close-sm ms-auto" onclick="this.parentElement.remove()"></button>';
            container.appendChild(toast);

            setTimeout(function () {
                toast.classList.add('fadeOut');
                setTimeout(function () { toast.remove(); }, 300);
            }, 4000);
        };

        /* Flash messages */
        document.querySelectorAll('.lt-flash-data').forEach(function (el) {
            window.ltToast(el.textContent.trim(), el.dataset.category);
        });

        /* ── Confirm Modal Helper ───────────────────────────────────────── */
        window.ltConfirm = function (message, callback) {
            const modal = document.getElementById('ltConfirmModal');
            if (!modal) { if (confirm(message)) callback(); return; }

            document.getElementById('ltConfirmBody').textContent = message;
            const btn = document.getElementById('ltConfirmBtn');
            const bsModal = bootstrap.Modal.getOrCreateInstance(modal);
            bsModal.show();

            const handler = function () {
                btn.removeEventListener('click', handler);
                bsModal.hide();
                callback();
            };
            btn.addEventListener('click', handler);
        };

        /* data-lt-confirm on links/buttons */
        document.addEventListener('click', function (e) {
            const target = e.target.closest('[data-lt-confirm]');
            if (!target) return;
            e.preventDefault();
            const msg = target.getAttribute('data-lt-confirm');
            const href = target.getAttribute('href') || target.getAttribute('data-href');
            const form = target.closest('form');

            window.ltConfirm(msg, function () {
                if (href) {
                    window.location.href = href;
                } else if (form) {
                    form.submit();
                }
            });
        });

        /* ── Animate Count Up ───────────────────────────────────────────── */
        window.animateCountUp = function (el, target) {
            const duration = 1500;
            const start = 0;
            const startTime = performance.now();

            function update(now) {
                const elapsed = now - startTime;
                const progress = Math.min(elapsed / duration, 1);
                const eased = 1 - Math.pow(1 - progress, 3);
                el.textContent = Math.floor(start + (target - start) * eased);
                if (progress < 1) requestAnimationFrame(update);
                else el.textContent = target;
            }
            requestAnimationFrame(update);
        };

        document.querySelectorAll('[data-count-up]').forEach(function (el) {
            const target = parseInt(el.getAttribute('data-count-up'), 10);
            if (!isNaN(target)) window.animateCountUp(el, target);
        });

        /* ── Keyboard Shortcuts ─────────────────────────────────────────── */
        document.addEventListener('keydown', function (e) {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;
            if (e.target.isContentEditable) return;

            if (e.key === '?' && e.shiftKey) {
                e.preventDefault();
                const m = document.getElementById('shortcutsModal');
                if (m) bootstrap.Modal.getOrCreateInstance(m).toggle();
                return;
            }

            if (e.altKey) {
                switch (e.key) {
                    case 'd':
                        e.preventDefault();
                        const dashLink = document.querySelector('.lt-sidebar-link[href*="dashboard"]');
                        if (dashLink) dashLink.click();
                        break;
                    case 'n':
                        e.preventDefault();
                        const newBtn = document.querySelector('[data-shortcut="new"]');
                        if (newBtn) newBtn.click();
                        break;
                    case 's':
                        e.preventDefault();
                        const searchInput = document.querySelector('.dataTables_filter input, input[name="search"]');
                        if (searchInput) searchInput.focus();
                        break;
                    case 't':
                        e.preventDefault();
                        if (themeToggle) themeToggle.click();
                        break;
                }
            }
        });

        /* ── Quick View Panel ───────────────────────────────────────────── */
        const quickView = document.getElementById('quickViewPanel');
        const quickViewBody = document.getElementById('quickViewBody');

        window.openQuickView = function (url) {
            if (!quickView || !quickViewBody) return;
            quickViewBody.innerHTML = '<div class="text-center py-5"><div class="spinner-border text-secondary"></div></div>';
            quickView.classList.add('open');

            fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' }})
                .then(r => r.text())
                .then(html => { quickViewBody.innerHTML = html; })
                .catch(() => { quickViewBody.innerHTML = '<div class="text-center py-5 text-muted">Failed to load</div>'; });
        };

        window.closeQuickView = function () {
            if (quickView) quickView.classList.remove('open');
        };

        document.addEventListener('click', function (e) {
            const trigger = e.target.closest('[data-quick-view]');
            if (trigger) {
                e.preventDefault();
                window.openQuickView(trigger.getAttribute('data-quick-view'));
            }
        });

        /* ── Drag & Drop Upload ─────────────────────────────────────────── */
        document.querySelectorAll('.lt-upload-zone').forEach(function (zone) {
            const input = zone.querySelector('input[type="file"]');
            if (!input) return;

            zone.addEventListener('click', function () { input.click(); });
            zone.addEventListener('dragover', function (e) { e.preventDefault(); zone.classList.add('dragover'); });
            zone.addEventListener('dragleave', function () { zone.classList.remove('dragover'); });
            zone.addEventListener('drop', function (e) {
                e.preventDefault();
                zone.classList.remove('dragover');
                input.files = e.dataTransfer.files;
                input.dispatchEvent(new Event('change'));
            });
            input.addEventListener('change', function () {
                if (input.files.length) {
                    zone.querySelector('.lt-upload-text').textContent = input.files[0].name;
                }
            });
        });

        /* ── Attachment Delete ───────────────────────────────────────────── */
        document.addEventListener('click', function (e) {
            const target = e.target.closest('[data-delete-attachment]');
            if (!target) return;
            e.preventDefault();
            const id = target.getAttribute('data-delete-attachment');
            window.ltConfirm('Delete this attachment?', function () {
                fetch('/api/attachments/' + id + '/delete', {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': csrfToken
                    }
                })
                .then(r => r.json())
                .then(data => {
                    if (data.status === 'ok') {
                        target.closest('.lt-attachment-item, tr, .list-group-item')?.remove();
                        window.ltToast('Attachment deleted', 'success');
                    } else {
                        window.ltToast(data.error || 'Failed', 'danger');
                    }
                })
                .catch(() => window.ltToast('Error deleting attachment', 'danger'));
            });
        });

        /* ── Filter Chips ───────────────────────────────────────────────── */
        document.addEventListener('click', function (e) {
            if (e.target.closest('.lt-chip-remove')) {
                const chip = e.target.closest('.lt-filter-chip');
                const field = chip?.dataset.field;
                if (field) {
                    const input = document.querySelector('[name="' + field + '"]');
                    if (input) {
                        input.value = '';
                        // If select2, trigger
                        if (input.classList.contains('select2-hidden-accessible')) {
                            $(input).val(null).trigger('change');
                        }
                    }
                    chip.remove();
                    // Submit filter form
                    const form = document.querySelector('form.lt-filter-form');
                    if (form) form.submit();
                }
            }
        });

        /* ── timeAgo ────────────────────────────────────────────────────── */
        window.timeAgo = function (dateStr) {
            const date = new Date(dateStr);
            const now = new Date();
            const diff = Math.floor((now - date) / 1000);

            if (diff < 60) return 'just now';
            if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
            if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
            if (diff < 604800) return Math.floor(diff / 86400) + 'd ago';
            return date.toLocaleDateString();
        };

        /* ── Password Show/Hide Toggle ──────────────────────────────────── */
        document.querySelectorAll('.password-toggle').forEach(function (btn) {
            btn.addEventListener('click', function () {
                const input = btn.closest('.position-relative')?.querySelector('input');
                if (!input) return;
                const isPassword = input.type === 'password';
                input.type = isPassword ? 'text' : 'password';
                const icon = btn.querySelector('i');
                if (icon) {
                    icon.className = isPassword ? 'bi bi-eye-slash' : 'bi bi-eye';
                }
            });
        });

        /* ── DataTables defaults ────────────────────────────────────────── */
        if (typeof $.fn.dataTable !== 'undefined') {
            $.extend(true, $.fn.dataTable.defaults, {
                language: {
                    search: '',
                    searchPlaceholder: 'Search…',
                    lengthMenu: 'Show _MENU_',
                    info: '_START_–_END_ of _TOTAL_',
                    paginate: { previous: '‹', next: '›' }
                },
                pageLength: 25,
                dom: "<'row'<'col-sm-6'l><'col-sm-6'f>>" +
                     "<'row'<'col-12'tr>>" +
                     "<'row'<'col-sm-5'i><'col-sm-7'p>>",
            });

            $(document).on('init.dt', function (_e, settings) {
                const $table = $(settings.nTable);
                const $wrapper = $table.closest('.dataTables_wrapper');
                if (!$wrapper.length) return;

                const $dtShell = $wrapper.parent('.lt-dt-shell');
                if (!$dtShell.length) return;

                const $bulkShell = $dtShell.prev('.lt-bulk-shell');
                if (!$bulkShell.length) return;

                const $filter = $wrapper.find('.dataTables_filter').first();
                const $length = $wrapper.find('.dataTables_length').first();

                if ($filter.length) {
                    let $filterSlot = $bulkShell.find('.lt-bulk-filter');
                    if (!$filterSlot.length) {
                        $filterSlot = $('<div class="lt-bulk-filter"></div>');
                        $bulkShell.append($filterSlot);
                    }
                    $filterSlot.append($filter);
                }

                if ($length.length) {
                    const $infoCol = $wrapper.find('.dataTables_info').first().closest('[class*="col-"]');
                    if ($infoCol.length) {
                        $infoCol.addClass('lt-bottom-info');
                        $infoCol.prepend($length);
                    }
                }

                const $topRow = $wrapper.children('.row').first();
                if ($topRow.length && !$topRow.find('.dataTables_filter, .dataTables_length').length) {
                    $topRow.remove();
                }
            });
        }

        /* ── Select2 Init ───────────────────────────────────────────────── */
        if (typeof $.fn.select2 !== 'undefined') {
            $('select.select2').select2({
                theme: 'bootstrap-5',
                allowClear: true,
                placeholder: 'Select…'
            });
        }

        /* ── Auto-refresh button ────────────────────────────────────────── */
        const refreshBtn = document.getElementById('refreshBtn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', function () {
                location.reload();
            });
        }

    }); // DOMContentLoaded
})();
