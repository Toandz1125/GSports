'use strict';

document.addEventListener('DOMContentLoaded', function () {
  var form = document.querySelector('[data-booking-time-form]');
  if (!form) {
    return;
  }

  var grid = form.querySelector('[data-time-block-grid]');
  var startInput = form.querySelector('#id_start_time');
  var endInput = form.querySelector('#id_end_time');
  var fieldInput = form.querySelector('#id_field');
  var dateInput = form.querySelector('#id_booking_date');
  var errorBox = form.querySelector('[data-time-block-error]');
  var availabilityUrl = form.getAttribute('data-availability-url');
  var serviceSection = form.querySelector('[data-service-section]');

  if (!grid || !startInput || !endInput) {
    return;
  }

  var maxDurationHours = Number(grid.getAttribute('data-max-duration-hours') || 4);
  var maxDurationMinutes = maxDurationHours * 60;
  var unavailableMessage = 'Khung giờ đã chọn có thời gian đã được đặt. Vui lòng chọn khung giờ khác.';
  var maxDurationMessage = 'Thời lượng đặt sân không được vượt quá 4 tiếng.';
  var availabilityRequestId = 0;

  function getButtons() {
    return Array.prototype.slice.call(grid.querySelectorAll('.time-block'));
  }

  function toMinutes(value) {
    if (!value) {
      return null;
    }

    var parts = value.split(':');
    if (parts.length !== 2) {
      return null;
    }

    var hours = Number(parts[0]);
    var minutes = Number(parts[1]);

    if (!Number.isInteger(hours) || !Number.isInteger(minutes)) {
      return null;
    }

    return (hours * 60) + minutes;
  }

  function setError(message) {
    if (!errorBox) {
      return;
    }
    errorBox.textContent = message || '';
    errorBox.classList.toggle('is-visible', Boolean(message));
  }

  function isUnavailableTime(timeValue) {
    return getButtons().some(function (button) {
      return button.getAttribute('data-time') === timeValue
        && button.classList.contains('is-unavailable');
    });
  }

  function rangeContainsUnavailable(startTime, endTime) {
    var startMinutes = toMinutes(startTime);
    var endMinutes = toMinutes(endTime);

    if (startMinutes === null || endMinutes === null) {
      return false;
    }

    return getButtons().some(function (button) {
      var buttonMinutes = toMinutes(button.getAttribute('data-time'));
      return button.classList.contains('is-unavailable')
        && buttonMinutes !== null
        && buttonMinutes >= startMinutes
        && buttonMinutes <= endMinutes;
    });
  }

  function updateSelection() {
    var startTime = startInput.value;
    var endTime = endInput.value;
    var startMinutes = toMinutes(startTime);
    var endMinutes = toMinutes(endTime);

    getButtons().forEach(function (button) {
      var buttonTime = button.getAttribute('data-time');
      var buttonMinutes = toMinutes(buttonTime);
      var isSelected = false;

      if (startTime && endTime && startMinutes !== null && endMinutes !== null) {
        isSelected = buttonMinutes !== null
          && buttonMinutes >= startMinutes
          && buttonMinutes <= endMinutes;
      } else if (startTime) {
        isSelected = buttonTime === startTime;
      }

      if (button.classList.contains('is-unavailable')) {
        isSelected = false;
      }

      button.classList.toggle('is-selected', isSelected);
      button.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
    });
  }

  function clearSelection(message) {
    startInput.value = '';
    endInput.value = '';
    setError(message || '');
    updateSelection();
  }

  function selectStart(timeValue) {
    startInput.value = timeValue;
    endInput.value = '';
    setError('');
    updateSelection();
  }

  function selectRange(startTime, endTime) {
    var startMinutes = toMinutes(startTime);
    var endMinutes = toMinutes(endTime);

    if (startMinutes === null || endMinutes === null || endMinutes <= startMinutes) {
      selectStart(endTime);
      return;
    }

    if (endMinutes - startMinutes > maxDurationMinutes) {
      endInput.value = '';
      setError(maxDurationMessage);
      updateSelection();
      return;
    }

    if (rangeContainsUnavailable(startTime, endTime)) {
      endInput.value = '';
      setError(unavailableMessage);
      updateSelection();
      return;
    }

    startInput.value = startTime;
    endInput.value = endTime;
    setError('');
    updateSelection();
  }

  function validateCurrentSelection() {
    var startTime = startInput.value;
    var endTime = endInput.value;
    var startMinutes = toMinutes(startTime);
    var endMinutes = toMinutes(endTime);

    if (startTime && isUnavailableTime(startTime)) {
      clearSelection(unavailableMessage);
      return;
    }

    if (endTime && isUnavailableTime(endTime)) {
      clearSelection(unavailableMessage);
      return;
    }

    if (startTime && endTime) {
      if (
        startMinutes === null
        || endMinutes === null
        || endMinutes <= startMinutes
        || endMinutes - startMinutes > maxDurationMinutes
      ) {
        clearSelection(maxDurationMessage);
        return;
      }

      if (rangeContainsUnavailable(startTime, endTime)) {
        clearSelection(unavailableMessage);
        return;
      }
    }

    updateSelection();
  }

  function renderBlocks(timeBlocks, unavailableBlocks) {
    var unavailableLookup = {};
    unavailableBlocks.forEach(function (timeValue) {
      unavailableLookup[timeValue] = true;
    });

    grid.innerHTML = '';
    timeBlocks.forEach(function (timeValue) {
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'time-block';
      button.setAttribute('data-time', timeValue);
      button.setAttribute('aria-pressed', 'false');
      button.textContent = timeValue;

      if (unavailableLookup[timeValue]) {
        button.classList.add('is-unavailable');
        button.disabled = true;
        button.setAttribute('aria-disabled', 'true');
      }

      grid.appendChild(button);
    });

    validateCurrentSelection();
  }

  function refreshAvailability() {
    if (!availabilityUrl) {
      return;
    }

    var params = new URLSearchParams();
    if (fieldInput && fieldInput.value) {
      params.set('field_id', fieldInput.value);
    }
    if (dateInput && dateInput.value) {
      params.set('booking_date', dateInput.value);
    }

    availabilityRequestId += 1;
    var requestId = availabilityRequestId;

    fetch(availabilityUrl + '?' + params.toString(), {
      headers: {
        Accept: 'application/json'
      }
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error('Availability request failed.');
        }
        return response.json();
      })
      .then(function (data) {
        if (requestId !== availabilityRequestId) {
          return;
        }
        renderBlocks(data.time_blocks || [], data.unavailable_blocks || []);
      })
      .catch(function () {
        setError('');
      });
  }

  grid.addEventListener('click', function (event) {
    var button = event.target.closest('.time-block');
    if (!button || !grid.contains(button) || button.disabled) {
      return;
    }

    var clickedTime = button.getAttribute('data-time');
    var currentStart = startInput.value;
    var currentEnd = endInput.value;
    var clickedMinutes = toMinutes(clickedTime);
    var startMinutes = toMinutes(currentStart);

    if (!currentStart || currentEnd) {
      selectStart(clickedTime);
      return;
    }

    if (clickedTime === currentStart) {
      clearSelection();
      return;
    }

    if (clickedMinutes === null || startMinutes === null || clickedMinutes < startMinutes) {
      selectStart(clickedTime);
      return;
    }

    selectRange(currentStart, clickedTime);
  });

  // Services are scoped to the selected field's venue. When the field changes we
  // fetch the new venue's services from the backend and rebuild the list, so the
  // frontend never keeps a stale or foreign-venue service. Quantities reset to 0.
  var serviceRequestId = 0;

  function formatPrice(rawPrice) {
    var amount = Number(rawPrice);
    if (!Number.isFinite(amount)) {
      return rawPrice;
    }
    return Math.round(amount).toLocaleString('vi-VN') + 'đ';
  }

  function buildServiceRow(service) {
    var row = document.createElement('tr');

    var nameCell = document.createElement('td');
    nameCell.textContent = service.name;
    row.appendChild(nameCell);

    var categoryCell = document.createElement('td');
    categoryCell.textContent = service.category || '-';
    row.appendChild(categoryCell);

    var priceCell = document.createElement('td');
    priceCell.textContent = formatPrice(service.price);
    row.appendChild(priceCell);

    var stockCell = document.createElement('td');
    stockCell.textContent = service.stock;
    row.appendChild(stockCell);

    var quantityCell = document.createElement('td');
    var input = document.createElement('input');
    input.type = 'number';
    input.name = 'service_quantity_' + service.id;
    input.min = '0';
    input.max = String(service.stock);
    input.value = '0';
    input.setAttribute('data-service-quantity', service.id);
    quantityCell.appendChild(input);
    row.appendChild(quantityCell);

    return row;
  }

  function refreshServices() {
    if (!serviceSection || !fieldInput) {
      return;
    }

    var tbody = serviceSection.querySelector('[data-service-tbody]');
    var tableWrap = serviceSection.querySelector('[data-service-table-wrap]');
    var emptyMessage = serviceSection.querySelector('[data-service-empty]');
    var urlTemplate = serviceSection.getAttribute('data-services-url-template');
    var fieldId = fieldInput.value;

    if (!tbody) {
      return;
    }

    // Always clear the list before (re)loading so a stale or foreign-venue
    // service can never linger or be submitted.
    tbody.innerHTML = '';

    function showEmpty() {
      if (tableWrap) {
        tableWrap.hidden = true;
      }
      if (emptyMessage) {
        emptyMessage.hidden = false;
      }
    }

    if (!urlTemplate || !fieldId) {
      showEmpty();
      return;
    }

    // Build an absolute URL for the services endpoint. This is intentionally
    // distinct from the availability endpoint so the two never collide.
    var requestUrl = urlTemplate.replace('__FIELD_ID__', fieldId);

    serviceRequestId += 1;
    var requestId = serviceRequestId;

    fetch(requestUrl, { headers: { Accept: 'application/json' } })
      .then(function (response) {
        if (!response.ok) {
          throw new Error('Service request failed.');
        }
        return response.json();
      })
      .then(function (data) {
        if (requestId !== serviceRequestId) {
          return;
        }
        if (!data || !Object.prototype.hasOwnProperty.call(data, 'services')) {
          console.error('Invalid services response', data);
          showEmpty();
          return;
        }
        var services = data.services || [];
        tbody.innerHTML = '';
        services.forEach(function (service) {
          tbody.appendChild(buildServiceRow(service));
        });
        var hasServices = services.length > 0;
        if (tableWrap) {
          tableWrap.hidden = !hasServices;
        }
        if (emptyMessage) {
          emptyMessage.hidden = hasServices;
        }
      })
      .catch(function () {
        showEmpty();
      });
  }

  if (fieldInput) {
    fieldInput.addEventListener('change', function () {
      refreshAvailability();
      refreshServices();
    });
  }
  if (dateInput) {
    dateInput.addEventListener('change', refreshAvailability);
  }

  var isNativeSubmit = false;
  form.addEventListener('submit', function (event) {
    if (isNativeSubmit) return;
    event.preventDefault();

    var formData = new FormData(form);
    var submitUrl = form.getAttribute('action') || window.location.href;

    fetch(submitUrl, {
      method: 'POST',
      body: formData,
      headers: {
        'Accept': 'application/json'
      }
    })
      .then(function (response) {
        if (response.status === 409) {
          return response.json().then(function (data) {
            clearSelection(data.message);
            refreshAvailability();
          });
        } else if (response.status === 201) {
          return response.json().then(function (data) {
            window.location.href = data.redirect_url;
          });
        } else {
          isNativeSubmit = true;
          form.submit();
        }
      })
      .catch(function () {
        isNativeSubmit = true;
        form.submit();
      });
  });

  setInterval(refreshAvailability, 10000);

  validateCurrentSelection();
});
