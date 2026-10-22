/*  CallRecorder - keeps recordings running across pages. */
(function (global) {
    'use strict';

    var S = {
        state: 'idle',           
        audioContext: null,
        callerStream: null,
        responderStream: null,
        callerAnalyser: null,
        responderAnalyser: null,
        
        // Measures each input before filtering or gain to show the raw audio levels. AnalyserNode does not change the recorded audio.
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

        // Captures each speaker separately for transcription without changing the mix recording.
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

    //// SUBSCRIBE: Registers an event handler and returns an unsubscribe function.
    function on(event, cb) {
        (listeners[event] = listeners[event] || []).push(cb);
        return function off() {
            var arr = listeners[event];
            if (!arr) return;
            var i = arr.indexOf(cb);
            if (i > -1) arr.splice(i, 1);
        };
    }

    /// BROADCAST: Sends an event to all handlers and ignores individual errors.
    function emit(event, payload) {
        (listeners[event] || []).slice().forEach(function (cb) {
            try { cb(payload); }
            catch (err) { console.error('CallRecorder "' + event + '" handler error:', err); }
        });
    }

    /// CLOCK: Converts seconds to "mm:ss" for the timer and banner.
    function formatted(secs) {
        secs = Math.max(0, secs | 0);
        var m = String(Math.floor(secs / 60)).padStart(2, '0');
        var s = String(secs % 60).padStart(2, '0');
        return m + ':' + s;
    }

    /// FLAG: True while recording; prevents duplicate actions.
    function isRecording() {
        return S.state === 'recording';
    }

    /// AGE: Seconds since recording started, or 0 when idle.
    function getElapsed() {
        return S.startTime ? Math.floor((Date.now() - S.startTime) / 1000) : 0;
    }

    /// SNAPSHOT: Returns the recording state and elapsed time.
    function getState() {
        return { state: S.state, elapsed: getElapsed() };
    }

    /// TAPS: Provides both speaker analysers for the waveforms.
    function getAnalysers() {
        return { callerAnalyser: S.callerAnalyser, responderAnalyser: S.responderAnalyser };
    }

    /// LINEAR->DB: Converts amplitude to dBFS; silence returns -Infinity.
    function toDb(linear) {
        return linear > 0 ? 20 * Math.log10(linear) : -Infinity;
    }

    /// MEASURE: Gets RMS and peak levels in dBFS, or null if silent. Uses dBFS to measure actual audio levels, not just waveform appearance.
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

    // Compares raw device audio with recorded audio to identify low volume caused by hardware, browser processing, or insufficient gain.
    function getLevels() {
        return {
            caller: { input: readLevel(S.callerInputAnalyser), mix: readLevel(S.callerAnalyser) },
            responder: { input: readLevel(S.responderInputAnalyser), mix: readLevel(S.responderAnalyser) }
        };
    }

    /// LAST-MIX: Stores the latest combined recording, or null if none exists.
    function getLatestBlob() {
        return S.latestBlob;
    }

    /// LAST-TRACKS: Stores separate caller and responder recordings for transcription.
    function getLatestTracks() {
        return { caller: S.latestCallerBlob, responder: S.latestResponderBlob };
    }

    /// LAST-URL: URL used to play the latest combined recording.
    function getLatestURL() {
        return S.latestURL;
    }

    /// COUNT-UP: Starts a 1-second timer that sends tick events to subscribers
    function startTimer() {
        stopTimer();
        S.timerInterval = setInterval(function () {
            emit('tick', { elapsed: getElapsed(), formatted: formatted(getElapsed()) });
        }, 1000);
    }

    /// CANCEL-TIMER: clears the tick interval. Void. Idempotent.
    function stopTimer() {
        if (S.timerInterval) {
            clearInterval(S.timerInterval);
            S.timerInterval = null;
        }
    }

    /// DISMANTLE: Stops both input streams, closes the AudioContext, and clears all audio nodes. Called after finalize.
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

    /// WRAP: Combines chunks into a Blob using the recorder's MIME type for call_setup.
    function buildBlob(chunks, recorder) {
        var type = (recorder && recorder.mimeType) || 'audio/webm';
        return new Blob(chunks, { type: type });
    }

    /// SEAL: Creates the mix and track blobs, saves the URL, cleans up the audio graph, and emits 'stop' once.
    function finalizeRecorded() {
        if (S.finalized) return;
        S.finalized = true;

        var blob = buildBlob(S.recordedChunks, S.mediaRecorder);
        S.recordedChunks = [];
        S.latestBlob = blob;

        // Only save a speaker's track if it contains audio, so failed recordings aren't treated as silence.
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

    // Stops all three recorders and waits for them to finish before creating the blobs.
    function handleRecorderStopped() {
        S.pendingStops -= 1;
        if (S.pendingStops <= 0) {
            S.pendingStops = 0;
            finalizeRecorded();
        }
    }

    /// HALT-ALL: stops the mix + both track recorders together
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

    /// ENGINE: Opens both audio devices, builds the audio graph, and starts three recorders. Returns the waveform analysers. Throws if a device is missing.
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

            // Sends each speaker's audio to a separate destination without changing the mix.
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

            // Uses Opus for each speaker's recording when supported, otherwise uses the browser default.
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

        // Gives the audio graph time to initialize before recording starts.
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

    /// PICK-MIME: Uses Opus for speaker tracks when supported, otherwise uses the browser default.
    function pickTrackOptions() {
        try {
            if (window.MediaRecorder && typeof MediaRecorder.isTypeSupported === 'function'
                && MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) {
                return { mimeType: 'audio/webm;codecs=opus' };
            }
        } catch (e) { /* fall through to the browser default */ }
        return undefined;
    }

    /// HALT: Stops all recorders when active; does nothing when idle.
    function stop() {
        if (S.state !== 'recording') return;
        stopAllRecorders();
    }

    // Restarts the audio clock when the responder returns to the tab.
    document.addEventListener('visibilitychange', function () {
        if (document.hidden) return;
        if (S.state === 'recording' && S.audioContext && S.audioContext.state === 'suspended') {
            S.audioContext.resume().catch(function () {});
        }
        emit('tick', { elapsed: getElapsed(), formatted: formatted(getElapsed()) });
    });

    /// REVEAL: Shows the recording banner when recording starts (live in base.html).
    function showBanner() {
        var b = document.getElementById('global-call-banner');
        if (b) b.classList.remove('hidden');
    }

    /// CONCEAL: Hides the recording banner when recording stops.
    function hideBanner() {
        var b = document.getElementById('global-call-banner');
        if (b) b.classList.add('hidden');
    }

    /// RETIME: Updates the banner timer on every tick.
    function updateBannerTimer(elapsed) {
        var t = document.getElementById('global-recording-timer');
        if (t) t.textContent = formatted(elapsed);
    }

    on('start', showBanner);
    on('tick', function (d) { updateBannerTimer(d.elapsed); });
    on('stop', hideBanner);

    // Shows the banner if recording is already active when the page loads.
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