'use strict';

document.addEventListener('DOMContentLoaded', function () {
  var startSelect = document.querySelector('[data-time-role="start"]');
  var endSelect = document.querySelector('[data-time-role="end"]');
  var maxDurationMinutes = 240;

  if (!startSelect || !endSelect) {
    return;
  }

  function toMinutes(value) {
    var parts = value.split(':');
    if (parts.length !== 2) {
      return null;
    }

    var hours = Number(parts[0]);
    var minutes = Number(parts[1]);

    if (!Number.isInteger(hours) || !Number.isInteger(minutes)) {
      return null;
    }

    return hours * 60 + minutes;
  }

  function updateEndTimeOptions() {
    var startMinutes = toMinutes(startSelect.value);
    var currentEndValue = endSelect.value;
    var currentEndStillValid = false;

    Array.prototype.forEach.call(endSelect.options, function (option) {
      if (!option.value || startMinutes === null) {
        option.disabled = false;
        return;
      }

      var endMinutes = toMinutes(option.value);
      var isValidEndTime = (
        endMinutes !== null
        && endMinutes > startMinutes
        && endMinutes - startMinutes <= maxDurationMinutes
      );

      option.disabled = !isValidEndTime;
      if (option.value === currentEndValue && isValidEndTime) {
        currentEndStillValid = true;
      }
    });

    if (currentEndValue && !currentEndStillValid) {
      endSelect.value = '';
    }
  }

  startSelect.addEventListener('change', updateEndTimeOptions);
  updateEndTimeOptions();
});
