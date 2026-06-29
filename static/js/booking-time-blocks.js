(function () {
    const filterForm = document.querySelector('[data-booking-filter-form]');
    if (!filterForm) return;

    const fieldSelect = filterForm.querySelector('[data-booking-field-select]');
    const dateInput = filterForm.querySelector('[data-booking-date-input]');

    [fieldSelect, dateInput].forEach((control) => {
        if (!control) return;
        control.addEventListener('change', () => {
            if (fieldSelect && fieldSelect.value && dateInput && dateInput.value) {
                filterForm.submit();
            }
        });
    });
})();
