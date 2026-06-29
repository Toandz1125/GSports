/*
 * Field manage screen — progressive enhancement for the 3-panel UI.
 *
 * Scoped strictly to the [data-field-manage] container so it cannot affect
 * other pages. Uses event delegation so AJAX-replaced panel content keeps
 * working. Every AJAX action degrades gracefully to a normal form submit /
 * link navigation when fetch is unavailable or fails.
 */
(function () {
    'use strict';

    var root = document.querySelector('[data-field-manage]');
    if (!root) return;

    function showToast(message) {
        if (!message) return;
        // Reuse the dashboard toast styling when present, otherwise no-op.
        var container = document.getElementById('toast-container');
        if (!container) {
            container = document.createElement('div');
            container.className = 'toast-container';
            container.id = 'toast-container';
            document.body.appendChild(container);
        }
        var toast = document.createElement('div');
        toast.className = 'toast toast--success';
        toast.setAttribute('role', 'alert');
        toast.innerHTML = '<span class="toast__text"></span>';
        toast.querySelector('.toast__text').textContent = message;
        container.appendChild(toast);
        setTimeout(function () { toast.remove(); }, 4000);
    }

    /* ── Tab / panel switching ── */
    function activateTab(tab) {
        var tabs = root.querySelectorAll('[data-field-tab]');
        var panels = root.querySelectorAll('[data-field-panel]');
        var matched = false;
        panels.forEach(function (panel) {
            var isTarget = panel.getAttribute('data-field-panel') === tab;
            if (isTarget) {
                panel.hidden = false;
                panel.classList.add('fm-panel--active');
                matched = true;
            } else {
                panel.hidden = true;
                panel.classList.remove('fm-panel--active');
            }
        });
        if (!matched) return false;
        tabs.forEach(function (link) {
            link.classList.toggle('fm-tab--active', link.getAttribute('data-field-tab') === tab);
        });
        try {
            var url = new URL(window.location.href);
            url.searchParams.set('tab', tab);
            window.history.replaceState({}, '', url);
        } catch (e) { /* ignore history errors */ }
        return true;
    }

    /* ── AJAX helpers ── */
    function getCsrf(form) {
        var input = form.querySelector('input[name=csrfmiddlewaretoken]');
        return input ? input.value : '';
    }

    function ajaxSubmit(form, onSuccess, onError) {
        if (typeof window.fetch !== 'function') return false;
        var data = new FormData(form);
        fetch(form.action, {
            method: 'POST',
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
            body: data,
            credentials: 'same-origin'
        }).then(function (resp) {
            return resp.json().then(function (payload) {
                return { ok: resp.ok, payload: payload };
            });
        }).then(function (result) {
            if (result.ok && result.payload && result.payload.ok) {
                onSuccess(result.payload);
            } else {
                onError(result.payload || {});
            }
        }).catch(function () {
            // Network/parse failure: fall back to a full, non-AJAX submit.
            form.submit();
        });
        return true;
    }

    function replacePanel(selector, html) {
        var panel = root.querySelector(selector);
        if (panel && typeof html === 'string') {
            panel.innerHTML = html;
        }
    }

    /* ── Delegated click handling ── */
    root.addEventListener('click', function (event) {
        // Tab switch
        var tabLink = event.target.closest('[data-field-tab]');
        if (tabLink && root.contains(tabLink)) {
            var tab = tabLink.getAttribute('data-field-tab');
            if (activateTab(tab)) {
                event.preventDefault();
            }
            return;
        }

        // Service: open inline price editor
        var editToggle = event.target.closest('[data-service-edit-toggle]');
        if (editToggle) {
            event.preventDefault();
            var card = editToggle.closest('[data-service-card]');
            var form = card && card.querySelector('[data-service-price-form]');
            if (form) {
                form.hidden = !form.hidden;
                if (!form.hidden) {
                    var input = form.querySelector('[data-service-price-input]');
                    if (input) { input.focus(); input.select(); }
                }
            }
            return;
        }

        // Service: cancel inline price editor
        var priceCancel = event.target.closest('[data-service-price-cancel]');
        if (priceCancel) {
            event.preventDefault();
            var pForm = priceCancel.closest('[data-service-price-form]');
            if (pForm) pForm.hidden = true;
            return;
        }
    });

    /* ── Pricing select-all ── */
    root.addEventListener('change', function (event) {
        var selectAll = event.target.closest('[data-pricing-select-all]');
        if (!selectAll) return;
        var panel = selectAll.closest('[data-pricing-panel]');
        if (!panel) return;
        panel.querySelectorAll('[data-pricing-block]').forEach(function (box) {
            box.checked = selectAll.checked;
        });
    });

    /* ── Pricing reset ── */
    root.addEventListener('reset', function (event) {
        var cancel = event.target.matches('[data-pricing-form]');
        if (!cancel) return;
        var sel = event.target.querySelector('[data-pricing-select-all]');
        if (sel) sel.checked = false;
    }, true);

    /* ── Delegated submit handling (AJAX with fallback) ── */
    root.addEventListener('submit', function (event) {
        var form = event.target;

        if (form.matches('[data-pricing-form]')) {
            var handled = ajaxSubmit(form, function (payload) {
                replacePanel('[data-field-panel="pricing"]', payload.html);
                showToast(payload.message);
            }, function (payload) {
                if (payload && payload.message) {
                    alert(payload.message);
                } else {
                    form.submit();
                }
            });
            if (handled) event.preventDefault();
            return;
        }

        if (form.matches('[data-service-toggle-form]') || form.matches('[data-service-price-form]')) {
            var done = ajaxSubmit(form, function (payload) {
                replacePanel('[data-field-panel="services"]', payload.html);
                showToast(payload.message);
            }, function (payload) {
                if (payload && payload.message) {
                    alert(payload.message);
                } else {
                    form.submit();
                }
            });
            if (done) event.preventDefault();
            return;
        }
    });
})();
