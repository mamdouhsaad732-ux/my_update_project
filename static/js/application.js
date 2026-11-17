/**
 * Shared frontend bootstrap for Medical PACS pages.
 * Fix: guard DOM/tool initialization to avoid null-reference errors
 * (e.g. "Cannot read properties of null (reading 'setSelectedTool')").
 */
(function (global) {
  'use strict';

  function safeInit(fn) {
    if (typeof fn !== 'function') return;
    var run = function () {
      try {
        fn();
      } catch (err) {
        console.error('Safe init error:', err);
      }
    };
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', run, { once: true });
    } else {
      run();
    }
  }

  function safeGetElement(id) {
    if (!id) return null;
    return document.getElementById(id) || null;
  }

  function safeSetSelectedTool(target, toolName) {
    // Guard: never call setSelectedTool on a null/undefined controller/app.
    if (!target || !toolName) return false;
    try {
      if (typeof target.setSelectedTool === 'function') {
        target.setSelectedTool(toolName);
        return true;
      }
      if (typeof target.setTool === 'function') {
        target.setTool(toolName);
        return true;
      }
      if (typeof target.getToolboxController === 'function') {
        var ctrl = target.getToolboxController();
        if (ctrl && typeof ctrl.setSelectedTool === 'function') {
          ctrl.setSelectedTool(toolName);
          return true;
        }
      }
    } catch (err) {
      console.warn('safeSetSelectedTool failed:', err);
    }
    return false;
  }

  global.MedicalPacsApp = global.MedicalPacsApp || {};
  global.MedicalPacsApp.safeInit = safeInit;
  global.MedicalPacsApp.safeGetElement = safeGetElement;
  global.MedicalPacsApp.safeSetSelectedTool = safeSetSelectedTool;

  // Backward-safe global: prevent crashes if legacy code calls setSelectedTool on null.
  if (typeof global.setSelectedTool !== 'function') {
    global.setSelectedTool = function (target, toolName) {
      return safeSetSelectedTool(target, toolName);
    };
  }

  /**
   * Throttled slice-step dispatcher for touch devices.
   *
   * DWV's native touch handler fires slice changes on every touchmove tick, which makes
   * swipe navigation hyper-sensitive on mobile (skipping many slices per gesture). This
   * helper paces navigation to at most one step per `intervalMs`, and optionally requires
   * a minimum swipe distance so tiny jitters do not step at all.
   *
   * Returns a controller: call `.step(delta)` from raw touch events; it decides whether
   * the gesture has traveled far enough / enough time has passed to advance one slice.
   */
  function createTouchThrottle(options) {
    var opts = options || {};
    var intervalMs = typeof opts.intervalMs === 'number' ? opts.intervalMs : 180;
    var minSwipePx = typeof opts.minSwipePx === 'number' ? opts.minSwipePx : 32;
    var axis = opts.axis === 'x' ? 'x' : 'y';

    var lastStepTime = 0;
    var startX = 0, startY = 0, tracking = false;
    var accumulated = 0;

    function now() {
      return Date.now ? Date.now() : new Date().getTime();
    }

    return {
      /** Begin tracking a gesture. */
      start: function (event) {
        var touch = event && event.touches ? event.touches[0] : null;
        if (!touch) return false;
        startX = touch.clientX;
        startY = touch.clientY;
        tracking = true;
        accumulated = 0;
        return true;
      },
      /**
       * Feed a move event; returns +1 / -1 when a slice step should fire, 0 otherwise.
       * Rate-limited to one step per interval and gated by minimum swipe distance.
       */
      move: function (event) {
        if (!tracking) return 0;
        var touch = event && event.touches ? event.touches[0] : null;
        if (!touch) return 0;

        var delta = axis === 'x'
          ? touch.clientX - startX
          : touch.clientY - startY;
        // Keep the reference anchored so slow drags keep producing steps one at a time.
        accumulated += delta;
        startX = touch.clientX;
        startY = touch.clientY;

        if (Math.abs(accumulated) < minSwipePx) return 0;

        var stamp = now();
        if (stamp - lastStepTime < intervalMs) return 0;

        lastStepTime = stamp;
        accumulated = 0;
        return accumulated === 0 ? (delta > 0 ? 1 : -1) : (delta > 0 ? 1 : -1);
      },
      /** End tracking (touchend/cancel). Returns and clears any pending step direction. */
      end: function () {
        tracking = false;
        accumulated = 0;
        return 0;
      },
      reset: function () {
        tracking = false;
        accumulated = 0;
        lastStepTime = 0;
      }
    };
  }

  /**
   * Attach throttled touch slice-navigation to a DWV-style viewer.
   * `stepFn(delta)` performs the actual slice change; swiping up/right advances.
   */
  function attachThrottledSliceNavigation(container, stepFn, options) {
    if (!container || typeof stepFn !== 'function') return null;
    var throttle = createTouchThrottle(options);
    var touchId = null;

    function onTouchStart(event) {
      if (event.touches && event.touches.length > 1) { throttle.reset(); touchId = null; return; }
      touchId = event.touches && event.touches[0] ? event.touches[0].identifier : null;
      throttle.start(event);
    }
    function onTouchMove(event) {
      if (touchId !== null && event.touches) {
        var found = null;
        for (var i = 0; i < event.touches.length; i++) {
          if (event.touches[i].identifier === touchId) { found = event.touches[i]; break; }
        }
        if (!found) return; // original finger lifted; ignore replacement touches
      }
      // preventDefault is NOT called: keep pinch-zoom/native behaviors intact.
      var dir = throttle.move(event);
      if (dir !== 0) {
        try { stepFn(dir); } catch (err) { console.warn('slice step failed:', err); }
      }
    }
    function onTouchEnd() {
      touchId = null;
      throttle.end();
    }

    container.addEventListener('touchstart', onTouchStart, { passive: true });
    container.addEventListener('touchmove', onTouchMove, { passive: true });
    container.addEventListener('touchend', onTouchEnd, { passive: true });
    container.addEventListener('touchcancel', onTouchEnd, { passive: true });

    return {
      destroy: function () {
        container.removeEventListener('touchstart', onTouchStart);
        container.removeEventListener('touchmove', onTouchMove);
        container.removeEventListener('touchend', onTouchEnd);
        container.removeEventListener('touchcancel', onTouchEnd);
      }
    };
  }

  global.MedicalPacsApp = global.MedicalPacsApp || {};
  global.MedicalPacsApp.safeInit = safeInit;
  global.MedicalPacsApp.safeGetElement = safeGetElement;
  global.MedicalPacsApp.safeSetSelectedTool = safeSetSelectedTool;
  global.MedicalPacsApp.createTouchThrottle = createTouchThrottle;
  global.MedicalPacsApp.attachThrottledSliceNavigation = attachThrottledSliceNavigation;
})(window);
