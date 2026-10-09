/*
    CallRecorder - persistent recording engine.

    The recording logic used to live inside the call-setup page, so any
    in-app (AJAX) navigation swapped that page away and the browser garbage
    collected the MediaRecorder, stopping the recording.

    This module is rooted on window.CallRecorder and loaded on every page,
    so the recording keeps running no matter which section the responder
    navigates to. Pages subscribe to events (start / tick / stop) to update
    their own UI.
*/
(function (global) {
    'use strict';

    var S = {
        state: 'idle',              // 'idle' | 'recording'
        audioContext: null,
        callerStream: null,
        responderStream: null,
        callerAnalyser: null,
        responderAnalyser: null,
        // Diagnostic-only taps taken straight off each input, before any
        // filtering or gain, so the level meter can show what the hardware and
        // the browser's own DSP actually delivered. An AnalyserNode passes
        // audio through, so these do not alter what is recorded.
        callerInputAnalyser: null,
        responderInputAnalyser: null,
        levelBuffer: null,
        mixerDestination: null,
        mediaRecorder: null,
        recordedChunks: [],
        startTime: 0,
        timerInterval: null,
        latestBlob: null,
        latestURL: null,

        // Isolated per-speaker taps. These are fed from the same analyser
        // nodes that feed the mix, so the mix recording itself is untouched
        // while we still capture each side on its own for transcription.
        callerTrackDestination: null,
        responderTrackDestination: null,
        callerTrackRecorder: null,
        responderTrackRecorder: null,
        callerTrackChunks: [],
        responderTrackChunks: [],
        latestCallerBlob: null,
        latestResponderBlob: null,
        pendingStops: 0,
        finalized: true
    };

    var listeners = {};

    function on(event, cb) {
        (listeners[event] = listeners[event] || []).push(cb);
        return function off() {
            var arr = listeners[event];
            if (!arr) return;
            var i = arr.indexOf(cb);
            if (i > -1) arr.splice(i, 1);
        };
    }

    function emit(event, payload) {
        (listeners[event] || []).slice().forEach(function (cb) {
            try { cb(payload); }
            catch (err) { console.error('CallRecorder "' + event + '" handler error:', err); }
        });
    }

    function formatted(secs) {
        secs = Math.max(0, secs | 0);
        var m = String(Math.floor(secs / 60)).padStart(2, '0');
        var s = String(secs % 60).padStart(2, '0');
        return m + ':' + s;
    }

    function isRecording() {
        return S.state === 'recording';
    }

    function getElapsed() {
        return S.startTime ? Math.floor((Date.now() - S.startTime) / 1000) : 0;
    }

    function getState() {
        return { state: S.state, elapsed: getElapsed() };
    }

    function getAnalysers() {
        return { callerAnalyser: S.callerAnalyser, responderAnalyser: S.responderAnalyser };
    }

    function toDb(linear) {
        return linear > 0 ? 20 * Math.log10(linear) : -Infinity;
    }

    // Reads one analyser's float time-domain data and reports true dBFS, which
    // is what tells us whether a side is genuinely quiet rather than merely
    // looking quiet on the waveform.
    function readLevel(analyser) {
        if (!analyser) return null;
        var size = analyser.fftSize || 2048;
        if (!S.levelBuffer || S.levelBuffer.length !== size) {
            S.levelBuffer = new Float32Array(size);
        }
        var buf = S.levelBuffer;
        try { analyser.getFloatTimeDomainData(buf); }
        catch (e) { return null; }

        var sum = 0, peak = 0;
        for (var i = 0; i < size; i++) {
            var v = buf[i];
            sum += v * v;
            var a = v < 0 ? -v : v;
            if (a > peak) peak = a;
        }
        var rms = Math.sqrt(sum / size);
        if (!(rms > 0)) return null;
        return { rms: toDb(rms), peak: toDb(peak) };
    }

    // input = straight off the device, mix = what actually reaches the
    // recording. Comparing the two tells us whether a quiet side is a hardware
    // or browser-DSP problem, or just not enough gain.
    function getLevels() {
        return {
            caller: { input: readLevel(S.callerInputAnalyser), mix: readLevel(S.callerAnalyser) },
            responder: { input: readLevel(S.responderInputAnalyser), mix: readLevel(S.responderAnalyser) }
        };
    }

    function getLatestBlob() {
        return S.latestBlob;
    }

    function getLatestTracks() {
        return { caller: S.latestCallerBlob, responder: S.latestResponderBlob };
    }

    function getLatestURL() {
        return S.latestURL;
    }

    function startTimer() {
        stopTimer();
        S.timerInterval = setInterval(function () {
            emit('tick', { elapsed: getElapsed(), formatted: formatted(getElapsed()) });
        }, 1000);
    }

    function stopTimer() {
        if (S.timerInterval) {
            clearInterval(S.timerInterval);
            S.timerInterval = null;
        }
    }

    function teardownGraph() {
        [S.callerStream, S.responderStream].forEach(function (stream) {
            if (stream) stream.getTracks().forEach(function (track) { try { track.stop(); } catch (e) {} });
        });
        if (S.audioContext && S.audioContext.state !== 'closed') {
            try { S.audioContext.close(); } catch (e) {}
        }
        S.callerStream = null;
        S.responderStream = null;
        S.callerAnalyser = null;
        S.responderAnalyser = null;
        S.callerInputAnalyser = null;
        S.responderInputAnalyser = null;
        S.mixerDestination = null;
        S.callerTrackDestination = null;
        S.responderTrackDestination = null;
        S.audioContext = null;
    }

    function buildBlob(chunks, recorder) {
        var type = (recorder && recorder.mimeType) || 'audio/webm';
        return new Blob(chunks, { type: type });
    }

    function finalizeRecorded() {
        if (S.finalized) return;
        S.finalized = true;

        var blob = buildBlob(S.recordedChunks, S.mediaRecorder);
        S.recordedChunks = [];
        S.latestBlob = blob;

        // Only expose a per-speaker track if that recorder actually produced
        // audio, so a failed tap never masquerades as a silent conversation.
        S.latestCallerBlob = S.callerTrackChunks.length
            ? buildBlob(S.callerTrackChunks, S.callerTrackRecorder)
            : null;
        S.latestResponderBlob = S.responderTrackChunks.length
            ? buildBlob(S.responderTrackChunks, S.responderTrackRecorder)
            : null;
        S.callerTrackChunks = [];
        S.responderTrackChunks = [];

        if (S.latestURL) { try { URL.revokeObjectURL(S.latestURL); } catch (e) {} }
        S.latestURL = URL.createObjectURL(blob);
        S.state = 'idle';
        stopTimer();
        teardownGraph();
        S.mediaRecorder = null;
        S.callerTrackRecorder = null;
        S.responderTrackRecorder = null;
        emit('stop', {
            blob: blob,
            url: S.latestURL,
            callerBlob: S.latestCallerBlob,
            responderBlob: S.latestResponderBlob
        });
    }

    // All three recorders are stopped together; wait for every one of them to
    // flush before building the blobs so no track is truncated.
    function handleRecorderStopped() {
        S.pendingStops -= 1;
        if (S.pendingStops <= 0) {
            S.pendingStops = 0;
            finalizeRecorded();
        }
    }

    function stopAllRecorders() {
        var recorders = [S.mediaRecorder, S.callerTrackRecorder, S.responderTrackRecorder];
        var active = recorders.filter(function (r) { return r && r.state !== 'inactive'; });

        S.finalized = false;
        S.pendingStops = active.length;
        if (S.pendingStops === 0) { finalizeRecorded(); return; }

        active.forEach(function (recorder) {
            try { recorder.stop(); }
            catch (e) { console.error(e); handleRecorderStopped(); }
        });

        // Safety net so a recorder that never fires onstop cannot hang the UI.
        setTimeout(function () {
            if (!S.finalized) { S.pendingStops = 0; finalizeRecorded(); }
        }, 3000);
    }

    async function start(userOptions) {
        if (S.state === 'recording') {
            throw new Error('A recording is already in progress.');
        }
        var options = userOptions || {};
        var callerId = options.callerId;
        var responderId = options.responderId;
        if (!callerId || !responderId) {
            throw new Error('Both input devices must be selected.');
        }

        S.recordedChunks = [];
        S.callerTrackChunks = [];
        S.responderTrackChunks = [];
        S.latestBlob = null;
        S.latestCallerBlob = null;
        S.latestResponderBlob = null;

        var callerConstraints = Object.assign({ deviceId: { exact: callerId } }, options.callerConstraints || {});
        var responderConstraints = Object.assign({ deviceId: { exact: responderId } }, options.responderConstraints || {});

        S.callerStream = await navigator.mediaDevices.getUserMedia({ audio: callerConstraints });
        S.responderStream = await navigator.mediaDevices.getUserMedia({ audio: responderConstraints });

        try {
            S.audioContext = new (window.AudioContext || window.webkitAudioContext)();
            if (S.audioContext.state === 'suspended') await S.audioContext.resume();

            var callerSource = S.audioContext.createMediaStreamSource(S.callerStream);
            var responderSource = S.audioContext.createMediaStreamSource(S.responderStream);

            S.callerInputAnalyser = S.audioContext.createAnalyser();
            S.callerInputAnalyser.fftSize = 2048;
            S.responderInputAnalyser = S.audioContext.createAnalyser();
            S.responderInputAnalyser.fftSize = 2048;
            callerSource.connect(S.callerInputAnalyser);
            responderSource.connect(S.responderInputAnalyser);

            var callerFilter = S.audioContext.createBiquadFilter();
            callerFilter.type = 'highpass';
            callerFilter.frequency.value = 100;

            var responderFilter = S.audioContext.createBiquadFilter();
            responderFilter.type = 'highpass';
            responderFilter.frequency.value = 100;

            var callerGain = S.audioContext.createGain();
            callerGain.gain.value = 0.7;

            var responderCompressor = S.audioContext.createDynamicsCompressor();
            responderCompressor.threshold.value = -15;
            responderCompressor.knee.value = 10;
            responderCompressor.ratio.value = 4;
            responderCompressor.attack.value = 0.003;
            responderCompressor.release.value = 0.25;

            var responderGain = S.audioContext.createGain();
            responderGain.gain.value = 5.5;

            S.mixerDestination = S.audioContext.createMediaStreamDestination();

            S.callerAnalyser = S.audioContext.createAnalyser();
            S.responderAnalyser = S.audioContext.createAnalyser();
            S.callerAnalyser.fftSize = 2048;
            S.responderAnalyser.fftSize = 2048;

            callerSource.connect(callerFilter);
            callerFilter.connect(callerGain);
            callerGain.connect(S.callerAnalyser);
            S.callerAnalyser.connect(S.mixerDestination);

            responderSource.connect(responderFilter);
            responderFilter.connect(responderCompressor);
            responderCompressor.connect(responderGain);
            responderGain.connect(S.responderAnalyser);
            S.responderAnalyser.connect(S.mixerDestination);

            // Tap the same two signals into separate destinations. An
            // AnalyserNode passes audio through, so these branches carry the
            // exact caller/responder audio that feeds the mix without
            // altering what the mix records.
            S.callerTrackDestination = S.audioContext.createMediaStreamDestination();
            S.responderTrackDestination = S.audioContext.createMediaStreamDestination();
            S.callerAnalyser.connect(S.callerTrackDestination);
            S.responderAnalyser.connect(S.responderTrackDestination);

            S.mediaRecorder = new MediaRecorder(S.mixerDestination.stream);

            S.mediaRecorder.ondataavailable = function (event) {
                if (event.data && event.data.size > 0) S.recordedChunks.push(event.data);
            };

            S.mediaRecorder.onstop = function () {
                handleRecorderStopped();
            };

            S.mediaRecorder.onerror = function (err) {
                console.error('MediaRecorder error:', err);
                if (S.state === 'recording') stopAllRecorders();
            };

            // A per-speaker track only needs to be intelligible, so prefer Opus
            // where it exists and fall back to the browser default otherwise.
            var trackOptions = pickTrackOptions();

            S.callerTrackRecorder = new MediaRecorder(S.callerTrackDestination.stream, trackOptions);
            S.callerTrackRecorder.ondataavailable = function (event) {
                if (event.data && event.data.size > 0) S.callerTrackChunks.push(event.data);
            };
            S.callerTrackRecorder.onstop = function () {
                handleRecorderStopped();
            };
            S.callerTrackRecorder.onerror = function (err) {
                console.error('Caller track recorder error:', err);
            };

            S.responderTrackRecorder = new MediaRecorder(S.responderTrackDestination.stream, trackOptions);
            S.responderTrackRecorder.ondataavailable = function (event) {
                if (event.data && event.data.size > 0) S.responderTrackChunks.push(event.data);
            };
            S.responderTrackRecorder.onstop = function () {
                handleRecorderStopped();
            };
            S.responderTrackRecorder.onerror = function (err) {
                console.error('Responder track recorder error:', err);
            };
        } catch (err) {
            teardownGraph();
            throw err;
        }

        // Give the audio graph a moment to warm up before the recorders start.
        setTimeout(function () {
            [S.mediaRecorder, S.callerTrackRecorder, S.responderTrackRecorder].forEach(function (recorder) {
                if (recorder && recorder.state === 'inactive') {
                    try { recorder.start(200); } catch (e) { console.error(e); }
                }
            });
        }, 500);


        S.startTime = Date.now();
        S.state = 'recording';
        startTimer();

        emit('start', { elapsed: 0 });
        return { callerAnalyser: S.callerAnalyser, responderAnalyser: S.responderAnalyser };
    }

    function pickTrackOptions() {
        try {
            if (window.MediaRecorder && typeof MediaRecorder.isTypeSupported === 'function'
                && MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) {
                return { mimeType: 'audio/webm;codecs=opus' };
            }
        } catch (e) { /* fall through to the browser default */ }
        return undefined;
    }

    function stop() {
        if (S.state !== 'recording') return;
        stopAllRecorders();
    }

    // Recover the audio clock when the responder comes back to the tab.
    document.addEventListener('visibilitychange', function () {
        if (document.hidden) return;
        if (S.state === 'recording' && S.audioContext && S.audioContext.state === 'suspended') {
            S.audioContext.resume().catch(function () {});
        }
        emit('tick', { elapsed: getElapsed(), formatted: formatted(getElapsed()) });
    });

    // --- Persistent "Recording in Progress" banner (live in base.html) ---
    function showBanner() {
        var b = document.getElementById('global-call-banner');
        if (b) b.classList.remove('hidden');
    }

    function hideBanner() {
        var b = document.getElementById('global-call-banner');
        if (b) b.classList.add('hidden');
    }

    function updateBannerTimer(elapsed) {
        var t = document.getElementById('global-recording-timer');
        if (t) t.textContent = formatted(elapsed);
    }

    on('start', showBanner);
    on('tick', function (d) { updateBannerTimer(d.elapsed); });
    on('stop', hideBanner);

    // If the page we load is mid-recording (e.g. returning to the call page),
    // keep the banner consistent with the actual recorder state.
    document.addEventListener('DOMContentLoaded', function () {
        if (isRecording()) showBanner();
    });

    global.CallRecorder = {
        start: start,
        stop: stop,
        isRecording: isRecording,
        getState: getState,
        getElapsed: getElapsed,
        getAnalysers: getAnalysers,
        getLevels: getLevels,
        getLatestBlob: getLatestBlob,
        getLatestTracks: getLatestTracks,
        getLatestURL: getLatestURL,
        on: on
    };
})(window);