(function () {
    const filterForm = document.querySelector('[data-booking-filter-form]');
    if (!filterForm) return;

    const venueSelect = filterForm.querySelector('[data-booking-venue-select]');
    const fieldSelect = filterForm.querySelector('[data-booking-field-select]');
    const dateInput = filterForm.querySelector('[data-booking-date-input]');
    const venueFieldsUrlTemplate = filterForm.dataset.venueFieldsUrlTemplate || '';
    const STALE_FILTER_PARAMS = ['field', 'field_id', 'slot', 'selected_slots', 'start_time', 'end_time'];

    function clearSelectedSlots() {
        document.querySelectorAll('[data-slot-card].slot-card--selected').forEach((card) => {
            card.classList.remove('slot-card--selected');
        });
        document.querySelectorAll('[data-selected-slot-inputs]').forEach((holder) => {
            holder.innerHTML = '';
        });
        document.querySelectorAll('input[name="start_time"], input[name="end_time"]').forEach((input) => {
            input.value = '';
        });
    }

    function buildCleanFilterUrl() {
        const url = new URL(filterForm.action || window.location.pathname, window.location.origin);
        const params = new URLSearchParams();
        STALE_FILTER_PARAMS.forEach((param) => params.delete(param));
        url.search = params.toString();
        return url;
    }

    function venueFieldsUrl(venueValue) {
        if (!venueFieldsUrlTemplate || !venueValue) return '';
        return venueFieldsUrlTemplate.replace('/0/', `/${encodeURIComponent(venueValue)}/`);
    }

    function resetFieldOptions(message) {
        if (!fieldSelect) return;
        fieldSelect.innerHTML = '';
        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = message || '-- Chọn sân con --';
        fieldSelect.appendChild(placeholder);
        fieldSelect.value = '';
    }

    function populateFieldOptions(fields, selectedFieldValue) {
        if (!fieldSelect) return;
        resetFieldOptions('-- Chọn sân con --');
        fields.forEach((field) => {
            const option = document.createElement('option');
            option.value = String(field.id);
            option.dataset.venueId = venueSelect ? String(venueSelect.value || '') : '';
            option.textContent = field.name;
            if (selectedFieldValue && String(selectedFieldValue) === String(field.id)) {
                option.selected = true;
            }
            fieldSelect.appendChild(option);
        });
        fieldSelect.disabled = !fields.length;
    }

    function loadFieldsForVenue(venueValue, selectedFieldValue) {
        const url = venueFieldsUrl(venueValue);
        if (!fieldSelect || !url) return Promise.resolve();
        fieldSelect.disabled = true;
        resetFieldOptions(venueValue ? 'Đang tải sân con...' : 'Chọn cơ sở trước');
        if (!venueValue) return Promise.resolve();

        return fetch(url, {
            headers: {
                Accept: 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
            },
        })
            .then((response) => (response.ok ? response.json() : { ok: false, fields: [] }))
            .then((payload) => {
                const fields = payload && payload.ok && Array.isArray(payload.fields)
                    ? payload.fields
                    : [];
                populateFieldOptions(fields, selectedFieldValue);
            })
            .catch(() => {
                resetFieldOptions('-- Chọn sân con --');
                fieldSelect.disabled = true;
            });
    }

    function reloadBookingFilter(includeField) {
        clearSelectedSlots();
        const url = buildCleanFilterUrl();
        const venueValue = venueSelect ? venueSelect.value : '';
        const fieldValue = fieldSelect ? fieldSelect.value : '';
        const dateValue = dateInput ? dateInput.value : '';
        const selectedOption = fieldSelect && fieldSelect.selectedOptions.length
            ? fieldSelect.selectedOptions[0]
            : null;

        if (venueValue) url.searchParams.set('venue', venueValue);
        if (
            includeField
            && venueValue
            && fieldValue
            && selectedOption
            && String(selectedOption.dataset.venueId || '') === String(venueValue)
        ) {
            url.searchParams.set('field', fieldValue);
        }
        if (dateValue) url.searchParams.set('booking_date', dateValue);

        window.location.assign(url.toString());
    }

    if (venueSelect) {
        venueSelect.addEventListener('change', () => {
            if (fieldSelect) {
                fieldSelect.value = '';
                loadFieldsForVenue(venueSelect.value);
            }
            reloadBookingFilter(false);
        });
    }

    if (fieldSelect) {
        fieldSelect.addEventListener('change', () => {
            if (!venueSelect || !venueSelect.value) {
                fieldSelect.value = '';
                clearSelectedSlots();
                return;
            }
            reloadBookingFilter(true);
        });
    }

    if (dateInput) {
        dateInput.addEventListener('change', () => {
            reloadBookingFilter(true);
        });
    }

    if (
        venueSelect
        && venueSelect.value
        && fieldSelect
    ) {
        if (fieldSelect.options.length <= 1) {
            loadFieldsForVenue(venueSelect.value);
        } else {
            fieldSelect.disabled = false;
        }
    }
})();

(function () {
    function formatRemaining(milliseconds) {
        const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
        const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, '0');
        const seconds = String(totalSeconds % 60).padStart(2, '0');
        return `${minutes}:${seconds}`;
    }

    function fetchBookingStatus(statusUrl) {
        if (!statusUrl) return Promise.resolve(null);
        return fetch(statusUrl, {
            headers: {
                Accept: 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
            },
        }).then((response) => {
            if (!response.ok) return null;
            return response.json();
        }).catch(() => null);
    }

    function updateDetailStatus(payload, countdownElement) {
        if (!payload) return;
        const statusLabel = document.querySelector('[data-booking-status-label]');
        if (statusLabel && payload.status_display) {
            statusLabel.textContent = payload.status_display;
        }
        if (payload.status === 'CANCELLED') {
            if (countdownElement) {
                countdownElement.textContent = 'Đã huỷ';
            }
            document.querySelectorAll('[data-payment-action]').forEach((action) => {
                action.hidden = true;
            });
        }
    }

    function startCountdown(countdownElement, deadlineValue, statusUrl, onExpired) {
        if (!countdownElement || !deadlineValue) return null;
        const deadline = new Date(deadlineValue);
        if (Number.isNaN(deadline.getTime())) return null;

        countdownElement.hidden = false;
        let confirmed = false;
        const tick = () => {
            const remaining = deadline.getTime() - Date.now();
            countdownElement.textContent = `Còn ${formatRemaining(remaining)} để thanh toán`;
            if (remaining <= 0 && !confirmed) {
                confirmed = true;
                window.clearInterval(timerId);
                fetchBookingStatus(statusUrl).then((payload) => {
                    if (payload && payload.status === 'PENDING' && payload.payment_deadline) {
                        startCountdown(countdownElement, payload.payment_deadline, statusUrl, onExpired);
                        return;
                    }
                    updateDetailStatus(payload, countdownElement);
                    if (typeof onExpired === 'function') {
                        onExpired(payload);
                    }
                });
            }
        };
        const timerId = window.setInterval(tick, 1000);
        tick();
        return timerId;
    }

    document.querySelectorAll('[data-booking-countdown][data-countdown-deadline]').forEach((element) => {
        startCountdown(
            element,
            element.dataset.countdownDeadline,
            element.dataset.bookingStatusUrl,
            null,
        );
    });

    window.GSportsBookingCountdown = {
        start: startCountdown,
        fetchStatus: fetchBookingStatus,
    };
})();

(function () {
    const bookingForm = document.querySelector('[data-slot-booking-form]');
    if (!bookingForm) return;

    const selectedInputs = bookingForm.querySelector('[data-selected-slot-inputs]');
    const startInput = bookingForm.querySelector('input[name="start_time"]');
    const endInput = bookingForm.querySelector('input[name="end_time"]');
    const errorBox = bookingForm.querySelector('[data-booking-error]');
    const resultBox = bookingForm.querySelector('[data-booking-result]');
    const resultMessage = bookingForm.querySelector('[data-booking-result-message]');
    const selectedSlots = new Map();

    function parseMoney(value) {
        const amount = Number(value);
        return Number.isFinite(amount) ? amount : 0;
    }

    function formatVnd(amount) {
        const roundedAmount = Math.round(parseMoney(amount));
        return `${new Intl.NumberFormat('vi-VN').format(roundedAmount)}đ`;
    }

    function updateEstimate() {
        const fieldSubtotal = bookingForm.querySelector('[data-field-subtotal]');
        const serviceSubtotal = bookingForm.querySelector('[data-service-subtotal]');
        const grandTotal = bookingForm.querySelector('[data-grand-total]');

        let fieldTotal = 0;
        bookingForm.querySelectorAll('[data-slot-card].slot-card--selected').forEach((card) => {
            fieldTotal += parseMoney(card.dataset.slotPrice);
        });

        let serviceTotal = 0;
        bookingForm.querySelectorAll('[data-service-quantity]').forEach((input) => {
            const quantity = Math.max(0, parseMoney(input.value));
            const price = parseMoney(input.dataset.servicePrice);
            serviceTotal += quantity * price;
        });

        if (fieldSubtotal) fieldSubtotal.textContent = formatVnd(fieldTotal);
        if (serviceSubtotal) serviceSubtotal.textContent = formatVnd(serviceTotal);
        if (grandTotal) grandTotal.textContent = formatVnd(fieldTotal + serviceTotal);
    }

    function showError(message) {
        if (!errorBox) return;
        errorBox.textContent = message || 'Không thể tạo booking. Vui lòng thử lại.';
        errorBox.hidden = false;
    }

    function clearError() {
        if (!errorBox) return;
        errorBox.textContent = '';
        errorBox.hidden = true;
    }

    function setButtonSelected(button, selected) {
        if (!button) return;
        button.textContent = selected ? 'Bỏ chọn' : 'Chọn';
        button.classList.toggle('slot-booking-button--selected', selected);
        button.classList.toggle('btn--secondary', selected);
        button.classList.toggle('btn--primary', !selected);
        button.setAttribute('aria-pressed', selected ? 'true' : 'false');
    }

    function syncHiddenInputs() {
        if (!selectedInputs) return;
        selectedInputs.innerHTML = '';
        const values = Array.from(selectedSlots.keys());
        values.forEach((value) => {
            const input = document.createElement('input');
            input.type = 'hidden';
            input.name = 'slots';
            input.value = value;
            selectedInputs.appendChild(input);
        });

        if (values.length && values[0].includes('|')) {
            const parts = values[0].split('|');
            if (startInput) startInput.value = parts[0];
            if (endInput) endInput.value = parts[1];
        } else {
            if (startInput) startInput.value = '';
            if (endInput) endInput.value = '';
        }
    }

    function toggleSlot(card, button) {
        if (!card || !button || button.disabled) return;
        const value = card.dataset.slotValue || button.value;
        if (!value) return;

        if (selectedSlots.has(value)) {
            selectedSlots.delete(value);
            card.classList.remove('slot-card--selected');
            setButtonSelected(button, false);
        } else {
            selectedSlots.set(value, card);
            card.classList.add('slot-card--selected');
            setButtonSelected(button, true);
        }
        syncHiddenInputs();
        clearError();
        updateEstimate();
    }

    function resetSelectedSlots() {
        selectedSlots.forEach((card) => {
            card.classList.remove('slot-card--selected');
            setButtonSelected(card.querySelector('[data-slot-toggle]'), false);
        });
        selectedSlots.clear();
        syncHiddenInputs();
        updateEstimate();
    }

    function extractErrorMessage(payload) {
        if (!payload) return 'Không thể tạo booking. Vui lòng thử lại.';
        if (payload.message) return payload.message;
        if (payload.errors) {
            const errors = payload.errors;
            const keys = Object.keys(errors);
            if (keys.length) {
                const first = errors[keys[0]];
                if (Array.isArray(first)) return first[0];
                if (typeof first === 'string') return first;
            }
        }
        return 'Không thể tạo booking. Vui lòng thử lại.';
    }

    bookingForm.querySelectorAll('[data-slot-toggle]').forEach((button) => {
        button.addEventListener('click', (event) => {
            event.preventDefault();
            toggleSlot(button.closest('[data-slot-card]'), button);
        });
    });

    bookingForm.addEventListener('input', (event) => {
        if (event.target.matches('[data-service-quantity]')) {
            updateEstimate();
        }
    });

    bookingForm.addEventListener('change', (event) => {
        if (event.target.matches('[data-service-quantity]')) {
            updateEstimate();
        }
    });

    bookingForm.addEventListener('submit', (event) => {
        if (!selectedSlots.size) {
            event.preventDefault();
            showError('Vui lòng chọn ít nhất một khung giờ.');
            return;
        }

        event.preventDefault();
        clearError();
        syncHiddenInputs();

        const submitButton = bookingForm.querySelector('[data-booking-submit]');
        if (submitButton) submitButton.disabled = true;

        fetch(bookingForm.action || window.location.href, {
            method: 'POST',
            body: new FormData(bookingForm),
            headers: {
                Accept: 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
            },
        }).then((response) => {
            return response.json().then((payload) => ({ response, payload }));
        }).then(({ response, payload }) => {
            if (!response.ok) {
                showError(extractErrorMessage(payload));
                if (submitButton) submitButton.disabled = false;
                return;
            }

            // Booking created: go straight to the booking detail page. No success
            // panel / "Thanh toán" / "Chi tiết booking" buttons on this screen.
            // Keep the submit button disabled while navigating to avoid a double
            // submit. checkout_url is intentionally not used here anymore.
            resetSelectedSlots();
            if (resultBox) resultBox.hidden = false;
            if (resultMessage) {
                resultMessage.textContent = 'Đặt sân thành công, đang chuyển sang chi tiết booking...';
            }

            const target = payload.redirect_url || ('/dat-san/' + payload.booking_id + '/');
            window.location.assign(target);
        }).catch(() => {
            showError('Không thể tạo booking. Vui lòng thử lại.');
            if (submitButton) submitButton.disabled = false;
        });
    });

    updateEstimate();
})();
