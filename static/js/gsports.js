'use strict';

// Project-level progressive enhancement. Server routes keep their normal
// redirect/render behavior; AJAX requests update only the declared DOM target.

(function () {
  function getCookie(name) {
    var value = '; ' + document.cookie;
    var parts = value.split('; ' + name + '=');
    if (parts.length === 2) {
      return parts.pop().split(';').shift();
    }
    return '';
  }

  function getCsrfToken(form) {
    var input = form ? form.querySelector('input[name="csrfmiddlewaretoken"]') : null;
    return input ? input.value : getCookie('csrftoken');
  }

  function toAbsoluteUrl(url) {
    return new URL(url, window.location.origin);
  }

  function isJsonResponse(response) {
    var contentType = response.headers.get('Content-Type') || '';
    return contentType.indexOf('application/json') !== -1;
  }

  function setBusy(element, busy) {
    if (!element) {
      return;
    }
    var buttons = element.querySelectorAll('button[type="submit"], input[type="submit"]');
    Array.prototype.forEach.call(buttons, function (button) {
      button.disabled = busy;
      if (busy) {
        button.dataset.originalText = button.textContent;
        button.textContent = 'Đang xử lý...';
      } else if (button.dataset.originalText) {
        button.textContent = button.dataset.originalText;
        delete button.dataset.originalText;
      }
    });
  }

  function showAjaxMessage(message, level) {
    if (!message) {
      return;
    }

    var pageShell = document.querySelector('.page-shell') || document.body;
    var container = document.querySelector('.messages');
    if (!container) {
      container = document.createElement('div');
      container.className = 'messages';
      pageShell.insertBefore(container, pageShell.firstChild);
    }

    container.innerHTML = '';
    var alert = document.createElement('div');
    alert.className = 'alert alert-' + (level || 'info');
    alert.textContent = message;
    container.appendChild(alert);
  }

  function updateTarget(selector, html) {
    if (!selector || typeof html !== 'string') {
      return false;
    }
    var target = document.querySelector(selector);
    if (!target) {
      return false;
    }
    target.innerHTML = html;
    return true;
  }

  function handlePayload(payload, options) {
    options = options || {};
    var targetSelector = payload.refresh_target || options.targetSelector;
    var updated = false;

    if (payload.html) {
      updated = updateTarget(targetSelector, payload.html);
    }

    if (payload.message) {
      showAjaxMessage(payload.message, payload.ok === false ? 'danger' : 'success');
    }

    if (payload.refresh_url && targetSelector && !updated) {
      return refreshTarget(payload.refresh_url, targetSelector, options.pushUrl);
    }

    if (options.refreshUrl && targetSelector && !updated) {
      return refreshTarget(options.refreshUrl, targetSelector, options.pushUrl);
    }

    if (!updated && (payload.redirect_url || options.successUrl)) {
      window.location.href = payload.redirect_url || options.successUrl;
    }

    return Promise.resolve(payload);
  }

  function parseFetchResponse(response) {
    if (!isJsonResponse(response)) {
      return response.text().then(function (text) {
        if (!response.ok) {
          throw new Error(text || 'HTTP ' + response.status);
        }
        return { ok: true, html: text };
      });
    }

    return response.json().then(function (payload) {
      if (!response.ok) {
        var message = payload.message || payload.error || ('HTTP ' + response.status);
        var error = new Error(message);
        error.payload = payload;
        throw error;
      }
      return payload;
    });
  }

  function refreshTarget(url, targetSelector, pushUrl) {
    return fetch(url, {
      headers: {
        Accept: 'application/json',
        'X-Requested-With': 'XMLHttpRequest',
      },
    })
      .then(parseFetchResponse)
      .then(function (payload) {
        if (payload.html) {
          updateTarget(targetSelector, payload.html);
        }
        if (pushUrl) {
          window.history.pushState({}, '', url);
        }
        return payload;
      });
  }

  function serializeGetForm(form) {
    var url = toAbsoluteUrl(form.getAttribute('action') || window.location.href);
    var params = new URLSearchParams();
    var formData = new FormData(form);
    formData.forEach(function (value, key) {
      if (value !== '') {
        params.append(key, value);
      }
    });
    url.search = params.toString();
    return url.toString();
  }

  function submitAjaxForm(form) {
    var confirmMessage = form.dataset.confirmMessage;
    if (confirmMessage && !window.confirm(confirmMessage)) {
      return;
    }

    var method = (form.getAttribute('method') || 'get').toUpperCase();
    var targetSelector = form.dataset.refreshTarget || '';
    var refreshUrl = form.dataset.refreshUrl || '';
    var successUrl = form.dataset.successUrl || '';
    var pushUrl = form.dataset.pushUrl === 'true';
    var url = method === 'GET'
      ? serializeGetForm(form)
      : toAbsoluteUrl(form.getAttribute('action') || window.location.href).toString();

    var options = {
      method: method,
      headers: {
        Accept: 'application/json',
        'X-Requested-With': 'XMLHttpRequest',
      },
    };

    if (method !== 'GET') {
      options.body = new FormData(form);
      options.headers['X-CSRFToken'] = getCsrfToken(form);
    }

    setBusy(form, true);

    fetch(url, options)
      .then(parseFetchResponse)
      .then(function (payload) {
        return handlePayload(payload, {
          targetSelector: targetSelector,
          refreshUrl: refreshUrl,
          successUrl: successUrl,
          pushUrl: pushUrl && method === 'GET',
        });
      })
      .then(function () {
        if (pushUrl && method === 'GET') {
          window.history.pushState({}, '', url);
        }
      })
      .catch(function (error) {
        if (error.payload) {
          handlePayload(error.payload, {
            targetSelector: targetSelector,
            refreshUrl: refreshUrl,
            successUrl: successUrl,
          });
          return;
        }
        if (window.console) {
          console.error('AJAX form failed:', error);
        }
        showAjaxMessage('Không thể xử lý thao tác. Vui lòng thử lại.', 'danger');
      })
      .finally(function () {
        setBusy(form, false);
      });
  }

  function clickAjaxLink(link) {
    var confirmMessage = link.dataset.confirmMessage;
    if (confirmMessage && !window.confirm(confirmMessage)) {
      return;
    }

    var targetSelector = link.dataset.refreshTarget || '';
    var pushUrl = link.dataset.pushUrl === 'true';
    var resetFormSelector = link.dataset.resetForm || '';
    refreshTarget(link.href, targetSelector, pushUrl)
      .then(function () {
        if (!resetFormSelector) {
          return;
        }
        var form = document.querySelector(resetFormSelector);
        if (form) {
          Array.prototype.forEach.call(form.elements, function (element) {
            if (!element.name || element.type === 'hidden' || element.type === 'submit' || element.type === 'button') {
              return;
            }
            if (element.type === 'checkbox' || element.type === 'radio') {
              element.checked = false;
            } else {
              element.value = '';
            }
          });
        }
        var ownerFieldSelect = document.getElementById('owner-field-filter');
        if (ownerFieldSelect && resetFormSelector.indexOf('owner-booking-filter') !== -1) {
          ownerFieldSelect.innerHTML = '<option value="">Vui lòng chọn cơ sở trước</option>';
          ownerFieldSelect.disabled = true;
        }
      })
      .catch(function (error) {
        if (window.console) {
          console.error('AJAX link failed:', error);
        }
        showAjaxMessage('Không thể tải dữ liệu. Vui lòng thử lại.', 'danger');
      });
  }

  function initDelegatedAjax() {
    document.addEventListener('submit', function (event) {
      var form = event.target.closest ? event.target.closest('form[data-ajax-form]') : null;
      if (!form) {
        return;
      }
      event.preventDefault();
      submitAjaxForm(form);
    });

    document.addEventListener('click', function (event) {
      var link = event.target.closest ? event.target.closest('a[data-ajax-link]') : null;
      if (!link) {
        return;
      }
      event.preventDefault();
      clickAjaxLink(link);
    });
  }

  function initOwnerFieldFilter() {
    var venueSelect = document.getElementById('owner-venue-filter');
    var fieldSelect = document.getElementById('owner-field-filter');

    if (!venueSelect || !fieldSelect) {
      return;
    }

    var filterForm = venueSelect.closest('[data-owner-booking-filter]');
    var fieldsUrl = venueSelect.dataset.fieldsUrl || (filterForm ? filterForm.dataset.fieldsUrl : '');

    if (!fieldsUrl) {
      return;
    }

    function resetFieldSelect(message, disabled) {
      fieldSelect.innerHTML = '';
      var option = document.createElement('option');
      option.value = '';
      option.textContent = message;
      fieldSelect.appendChild(option);
      fieldSelect.disabled = disabled !== false;
    }

    function populateFieldSelect(fields) {
      fieldSelect.innerHTML = '';

      if (!fields || fields.length === 0) {
        resetFieldSelect('Cơ sở này chưa có sân hoạt động', true);
        return;
      }

      var allOption = document.createElement('option');
      allOption.value = '';
      allOption.textContent = 'Tất cả sân';
      fieldSelect.appendChild(allOption);

      fields.forEach(function (field) {
        var option = document.createElement('option');
        option.value = String(field.id);
        option.textContent = field.name;
        fieldSelect.appendChild(option);
      });

      fieldSelect.disabled = false;
    }

    venueSelect.addEventListener('change', function () {
      var venueId = venueSelect.value;

      if (!venueId) {
        resetFieldSelect('Vui lòng chọn cơ sở trước', true);
        return;
      }

      resetFieldSelect('Đang tải sân...', true);

      fetch(fieldsUrl + '?venue_id=' + encodeURIComponent(venueId), {
        headers: {
          Accept: 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
        },
      })
        .then(parseFetchResponse)
        .then(function (payload) {
          populateFieldSelect(payload.fields || []);
        })
        .catch(function (error) {
          if (window.console) {
            console.error('Không thể tải danh sách sân:', error);
          }
          resetFieldSelect('Không thể tải danh sách sân', true);
        });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    initDelegatedAjax();
    initOwnerFieldFilter();
  });
})();
