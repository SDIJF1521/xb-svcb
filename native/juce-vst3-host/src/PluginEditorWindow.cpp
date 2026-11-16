#include "PluginEditorWindow.h"
#include "PluginRuntime.h"
#include <juce_audio_devices/juce_audio_devices.h>
#include <juce_audio_formats/juce_audio_formats.h>
#include <juce_gui_extra/juce_gui_extra.h>
#include <atomic>
#include <cmath>
#include <memory>

namespace xb::vst3
{
using namespace juce;

class PluginEditorWindow final : public DocumentWindow,
                                 private Timer,
                                 private HighResolutionTimer,
                                 private AudioIODeviceCallback,
                                 private AudioPlayHead
{
public:
    PluginEditorWindow (
        std::unique_ptr<AudioPluginInstance> pluginInstance,
        PluginDescription pluginDescription,
        const Request& request
    )
        : DocumentWindow (
            pluginDescription.name.isNotEmpty() ? pluginDescription.name : "VST3 Plugin",
            Colours::black,
            DocumentWindow::closeButton | DocumentWindow::minimiseButton
          ),
          plugin (std::move (pluginInstance)),
          description (std::move (pluginDescription)),
          stateOutput (request.stateOutput),
          transportControl (request.transportControl),
          monitorTimelineStart (request.monitorTimelineStart),
          monitorTimelineEnd (request.monitorTimelineEnd),
          projectDuration (request.projectDuration),
          requestedSampleRate (request.sampleRate),
          requestedBlockSize (request.blockSize),
          activeSampleRate (request.sampleRate),
          activeBlockSize (request.blockSize),
          effectCapable (canProcessAudioEffect (*plugin, description))
    {
        setUsingNativeTitleBar (true);
        setAlwaysOnTop (true);
        setDropShadowEnabled (true);
        setResizable (true, true);
        plugin->setPlayHead (this);

        std::unique_ptr<AudioProcessorEditor> editor (plugin->createEditorIfNeeded());
        if (editor == nullptr)
            editor.reset (new GenericAudioProcessorEditor (*plugin));

        auto width = jmax (420, editor->getWidth());
        auto height = jmax (260, editor->getHeight());
        setContentOwned (editor.release(), true);
        centreWithSize (width, height);
        setVisible (true);
        toFront (true);

        readerThread.startThread (Thread::Priority::high);

        if (request.monitorInput.existsAsFile())
            monitorReader = createBufferedReader (request.monitorInput);

        if (request.bedInput.existsAsFile())
            bedReader = createBufferedReader (request.bedInput);

        const auto inputChannels = jmax (1, plugin->getTotalNumInputChannels());
        const auto outputChannels = jmax (2, plugin->getTotalNumOutputChannels());
        processChannels = jmax (2, jmax (inputChannels, outputChannels));
        const auto capacity = jmax (8192, requestedBlockSize * 4);
        monitorBuffer.setSize (processChannels, capacity);
        dryBuffer.setSize (processChannels, capacity);
        bedBuffer.setSize (2, capacity);
        monitorReadBuffer.setSize (processChannels, 65536);
        bedReadBuffer.setSize (2, 65536);
        cachedPlugin = pluginRuntimeMetadata (*plugin, description);
        windowShownMs = Time::getMillisecondCounter();
        Timer::startTimer (30);
    }

    ~PluginEditorWindow() override
    {
        HighResolutionTimer::stopTimer();
        Timer::stopTimer();
        deviceManager.removeAudioCallback (this);
        deviceManager.closeAudioDevice();
        flushState (! finalStateCaptured);
        monitorReader.reset();
        bedReader.reset();
        readerThread.stopThread (2000);
        clearContentComponent();
        if (plugin != nullptr)
        {
            plugin->setPlayHead (nullptr);
            plugin->releaseResources();
        }
    }

    void closeButtonPressed() override
    {
        HighResolutionTimer::stopTimer();
        Timer::stopTimer();
        transportPlaying.store (false);
        outputEnabled.store (false);
        deviceManager.removeAudioCallback (this);
        deviceManager.closeAudioDevice();
        flushState (true);
        MessageManager::getInstance()->stopDispatchLoop();
    }

private:
    std::unique_ptr<AudioPluginInstance> plugin;
    PluginDescription description;
    File stateOutput;
    File transportControl;
    TimeSliceThread readerThread { "VST3 monitor read-ahead" };
    std::unique_ptr<AudioFormatReader> monitorReader;
    std::unique_ptr<AudioFormatReader> bedReader;
    AudioBuffer<float> monitorBuffer;
    AudioBuffer<float> dryBuffer;
    AudioBuffer<float> bedBuffer;
    AudioBuffer<float> monitorReadBuffer;
    AudioBuffer<float> bedReadBuffer;
    MidiBuffer monitorMidi;
    CriticalSection processLock;
    AudioDeviceManager deviceManager;
    std::atomic<bool> transportPlaying { false };
    std::atomic<bool> outputEnabled { false };
    std::atomic<bool> audioOutputReady { false };
    std::atomic<bool> transportEnded { false };
    std::atomic<int64> transportSamplePosition { 0 };
    std::atomic<int64> playHeadSamplePosition { 0 };
    std::atomic<int> silenceBlocksRemaining { 0 };
    std::atomic<double> monitorTimelineStart;
    std::atomic<double> monitorTimelineEnd;
    std::atomic<double> projectDuration;
    std::atomic<int64> monitorBlocks { 0 };
    std::atomic<float> monitorPeak { 0.0f };
    std::atomic<float> monitorOutputPeak { 0.0f };
    std::atomic<int64> silentOutputSamples { 0 };
    std::atomic<bool> safetyBypassed { false };
    double requestedSampleRate;
    int requestedBlockSize;
    std::atomic<double> activeSampleRate;
    std::atomic<int> activeBlockSize;
    int processChannels = 2;
    int lastTransportRevision = -1;
    int lastSeekRevision = -1;
    uint32 lastStateFlushMs = 0;
    uint32 lastParameterRefreshMs = 0;
    uint32 windowShownMs = 0;
    String audioDeviceName;
    String audioDeviceError;
    int outputLatencySamples = 0;
    var cachedPlugin;
    bool effectCapable = false;
    bool finalStateCaptured = false;
    bool audioOutputInitialised = false;

    std::unique_ptr<AudioFormatReader> createBufferedReader (const File& file)
    {
        AudioFormatManager formats;
        formats.registerBasicFormats();
        auto* source = formats.createReaderFor (file);
        if (source == nullptr)
            return {};

        auto buffered = std::make_unique<BufferingAudioReader> (
            source,
            readerThread,
            262144
        );
        buffered->setReadTimeout (2);
        return buffered;
    }

    void timerCallback() override
    {
        const auto now = Time::getMillisecondCounter();
        if (! audioOutputInitialised)
        {
            if (now - windowShownMs < 250)
                return;

            audioOutputInitialised = true;
            initialiseAudioOutput();
            if (! audioOutputReady.load())
                HighResolutionTimer::startTimer (
                    jlimit (
                        1,
                        50,
                        roundToInt (
                            1000.0 * static_cast<double> (requestedBlockSize)
                            / requestedSampleRate
                        )
                    )
                );
            readTransportControl();
            flushState (false);
            lastStateFlushMs = now;
            lastParameterRefreshMs = now;
            return;
        }

        readTransportControl();
        if (! transportPlaying.load (std::memory_order_relaxed)
            && now - lastParameterRefreshMs >= 500)
        {
            refreshCachedParameterValues();
            lastParameterRefreshMs = now;
        }
        if (now - lastStateFlushMs >= 250)
        {
            flushState (false);
            lastStateFlushMs = now;
        }
    }

    void hiResTimerCallback() override
    {
        if (audioOutputReady.load())
            return;
        processAudioBlock (nullptr, 0, requestedBlockSize, false);
    }

    void audioDeviceIOCallbackWithContext (
        const float* const*,
        int,
        float* const* outputChannelData,
        int numOutputChannels,
        int numSamples,
        const AudioIODeviceCallbackContext&
    ) override
    {
        processAudioBlock (outputChannelData, numOutputChannels, numSamples, true);
    }

    void audioDeviceAboutToStart (AudioIODevice* device) override
    {
        if (device == nullptr)
            return;
        activeSampleRate.store (device->getCurrentSampleRate());
        activeBlockSize.store (device->getCurrentBufferSizeSamples());
        outputLatencySamples = device->getOutputLatencyInSamples();
        audioDeviceName = device->getName();
    }

    void audioDeviceStopped() override
    {
        audioOutputReady.store (false);
    }

    Optional<PositionInfo> getPosition() const override
    {
        const auto rate = activeSampleRate.load (std::memory_order_relaxed);
        const auto sample = playHeadSamplePosition.load (std::memory_order_relaxed);
        const auto seconds = rate > 0.0 ? static_cast<double> (sample) / rate : 0.0;
        constexpr auto bpm = 120.0;
        const auto ppq = seconds * bpm / 60.0;

        PositionInfo position;
        position.setTimeInSamples (sample);
        position.setTimeInSeconds (seconds);
        position.setBpm (bpm);
        position.setTimeSignature (TimeSignature { 4, 4 });
        position.setPpqPosition (ppq);
        position.setPpqPositionOfLastBarStart (std::floor (ppq / 4.0) * 4.0);
        position.setIsPlaying (transportPlaying.load (std::memory_order_relaxed));
        position.setIsRecording (false);
        position.setIsLooping (false);
        return position;
    }

    void initialiseAudioOutput()
    {
        auto error = deviceManager.initialise (0, 2, nullptr, true);
        if (error.isNotEmpty())
        {
            audioDeviceError = error;
            return;
        }

        auto setup = deviceManager.getAudioDeviceSetup();
        setup.sampleRate = requestedSampleRate;
        setup.bufferSize = requestedBlockSize;
        auto setupError = deviceManager.setAudioDeviceSetup (setup, true);
        if (setupError.isNotEmpty())
            audioDeviceError = setupError;

        auto* device = deviceManager.getCurrentAudioDevice();
        if (device == nullptr)
        {
            if (audioDeviceError.isEmpty())
                audioDeviceError = "No audio output device is available";
            return;
        }

        const auto deviceRate = device->getCurrentSampleRate();
        const auto deviceBlock = device->getCurrentBufferSizeSamples();
        activeSampleRate.store (deviceRate);
        activeBlockSize.store (deviceBlock);
        outputLatencySamples = device->getOutputLatencyInSamples();
        audioDeviceName = device->getName();
        if (std::abs (deviceRate - requestedSampleRate) > 0.5
            || deviceBlock != requestedBlockSize)
        {
            plugin->releaseResources();
            preparePluginForStereo (*plugin, deviceRate, deviceBlock);
        }
        deviceManager.addAudioCallback (this);
        audioOutputReady.store (true);
    }

    void processAudioBlock (
        float* const* outputChannelData,
        int numOutputChannels,
        int numSamples,
        bool writeOutput
    )
    {
        for (int channel = 0; channel < numOutputChannels; ++channel)
            if (outputChannelData[channel] != nullptr)
                FloatVectorOperations::clear (outputChannelData[channel], numSamples);

        if (numSamples <= 0 || numSamples > monitorBuffer.getNumSamples())
            return;

        monitorBuffer.clear (0, numSamples);
        dryBuffer.clear (0, numSamples);
        bedBuffer.clear (0, numSamples);
        monitorMidi.clear();

        const auto playing = transportPlaying.load (std::memory_order_relaxed);
        auto shouldProcess = playing;
        if (! shouldProcess)
        {
            auto remaining = silenceBlocksRemaining.load (std::memory_order_relaxed);
            while (remaining > 0)
            {
                if (silenceBlocksRemaining.compare_exchange_weak (
                        remaining,
                        remaining - 1,
                        std::memory_order_relaxed))
                {
                    shouldProcess = true;
                    break;
                }
            }
        }
        if (! shouldProcess)
        {
            monitorPeak.store (0.0f, std::memory_order_relaxed);
            return;
        }

        const auto rate = activeSampleRate.load (std::memory_order_relaxed);
        const auto globalSample = playing
            ? transportSamplePosition.fetch_add (numSamples, std::memory_order_relaxed)
            : transportSamplePosition.load (std::memory_order_relaxed);
        playHeadSamplePosition.store (globalSample, std::memory_order_relaxed);
        const auto durationSamples = static_cast<int64> (
            std::llround (projectDuration.load (std::memory_order_relaxed) * rate)
        );
        const auto activeSamples = playing && durationSamples > 0
            ? static_cast<int> (jlimit<int64> (0, numSamples, durationSamples - globalSample))
            : (playing ? numSamples : 0);

        if (activeSamples > 0 && bedReader != nullptr)
            readTimelineAudio (
                *bedReader,
                bedBuffer,
                bedReadBuffer,
                0,
                globalSample,
                activeSamples,
                rate
            );

        auto targetSamples = 0;
        if (activeSamples > 0 && monitorReader != nullptr)
        {
            const auto targetStart = static_cast<int64> (
                std::llround (monitorTimelineStart.load (std::memory_order_relaxed) * rate)
            );
            const auto targetEnd = static_cast<int64> (
                std::llround (monitorTimelineEnd.load (std::memory_order_relaxed) * rate)
            );
            const auto overlapStart = jmax (globalSample, targetStart);
            const auto overlapEnd = jmin (globalSample + activeSamples, targetEnd);
            if (overlapEnd > overlapStart)
            {
                const auto destinationOffset = static_cast<int> (overlapStart - globalSample);
                const auto sourceStart = overlapStart - targetStart;
                targetSamples = static_cast<int> (overlapEnd - overlapStart);
                readTimelineAudio (
                    *monitorReader,
                    monitorBuffer,
                    monitorReadBuffer,
                    destinationOffset,
                    sourceStart,
                    targetSamples,
                    rate
                );
            }
        }

        if (targetSamples > 0)
        {
            auto peak = 0.0f;
            for (int channel = 0; channel < jmin (2, monitorBuffer.getNumChannels()); ++channel)
                peak = jmax (peak, monitorBuffer.getMagnitude (channel, 0, numSamples));
            monitorPeak.store (peak, std::memory_order_relaxed);
            monitorBlocks.fetch_add (1, std::memory_order_relaxed);
        }
        else
        {
            monitorPeak.store (0.0f, std::memory_order_relaxed);
        }

        for (int channel = 0; channel < monitorBuffer.getNumChannels(); ++channel)
            dryBuffer.copyFrom (
                channel,
                0,
                monitorBuffer,
                channel,
                0,
                numSamples
            );

        if (plugin != nullptr && effectCapable)
        {
            const ScopedLock lock (processLock);
            AudioBuffer<float> processView (
                monitorBuffer.getArrayOfWritePointers(),
                monitorBuffer.getNumChannels(),
                numSamples
            );
            plugin->processBlock (processView, monitorMidi);
        }

        auto outputPeak = 0.0f;
        auto outputFinite = true;
        for (int channel = 0; channel < jmin (2, monitorBuffer.getNumChannels()); ++channel)
        {
            auto* data = monitorBuffer.getWritePointer (channel);
            for (int sample = 0; sample < numSamples; ++sample)
            {
                if (! std::isfinite (data[sample]))
                {
                    outputFinite = false;
                    data[sample] = 0.0f;
                }
                outputPeak = jmax (outputPeak, std::abs (data[sample]));
            }
        }
        monitorOutputPeak.store (outputPeak, std::memory_order_relaxed);

        const auto inputPeak = monitorPeak.load (std::memory_order_relaxed);
        if (effectCapable && inputPeak > 0.0001f && (! outputFinite || outputPeak < 0.0000001f))
        {
            const auto accumulated = silentOutputSamples.fetch_add (
                numSamples,
                std::memory_order_relaxed
            ) + numSamples;
            const auto pluginLatency = plugin != nullptr ? plugin->getLatencySamples() : 0;
            const auto safetyThreshold = jmax<int64> (
                static_cast<int64> (rate * 0.5),
                static_cast<int64> (pluginLatency + numSamples * 4)
            );
            if (! outputFinite || accumulated >= safetyThreshold)
                safetyBypassed.store (true, std::memory_order_relaxed);
        }
        else if (outputFinite && outputPeak >= 0.0000001f)
        {
            silentOutputSamples.store (0, std::memory_order_relaxed);
            safetyBypassed.store (false, std::memory_order_relaxed);
        }

        if (! effectCapable || safetyBypassed.load (std::memory_order_relaxed))
            for (int channel = 0; channel < monitorBuffer.getNumChannels(); ++channel)
                monitorBuffer.copyFrom (
                    channel,
                    0,
                    dryBuffer,
                    channel,
                    0,
                    numSamples
                );

        if (writeOutput && playing && outputEnabled.load (std::memory_order_relaxed))
        {
            for (int channel = 0; channel < numOutputChannels; ++channel)
            {
                auto* output = outputChannelData[channel];
                if (output == nullptr)
                    continue;
                const auto sourceChannel = jmin (channel, monitorBuffer.getNumChannels() - 1);
                const auto bedChannel = jmin (channel, bedBuffer.getNumChannels() - 1);
                FloatVectorOperations::copy (output, bedBuffer.getReadPointer (bedChannel), activeSamples);
                FloatVectorOperations::add (output, monitorBuffer.getReadPointer (sourceChannel), activeSamples);
                for (int sample = 0; sample < activeSamples; ++sample)
                    output[sample] = jlimit (-0.99f, 0.99f, output[sample]);
            }
        }

        if (playing && durationSamples > 0 && globalSample + numSamples >= durationSamples)
        {
            transportSamplePosition.store (durationSamples, std::memory_order_relaxed);
            transportPlaying.store (false, std::memory_order_relaxed);
            transportEnded.store (true, std::memory_order_relaxed);
        }
    }

    static void readTimelineAudio (
        AudioFormatReader& reader,
        AudioBuffer<float>& destination,
        AudioBuffer<float>& scratch,
        int destinationOffset,
        int64 timelineSample,
        int samples,
        double timelineRate
    )
    {
        if (samples <= 0 || timelineRate <= 0.0)
            return;
        const auto ratio = reader.sampleRate / timelineRate;
        const auto exactStart = static_cast<double> (timelineSample) * ratio;
        const auto sourceStart = static_cast<int64> (std::floor (exactStart));
        const auto exactEnd = static_cast<double> (timelineSample + samples - 1) * ratio;
        const auto requestedSourceSamples = static_cast<int> (
            std::ceil (exactEnd) - static_cast<double> (sourceStart) + 2.0
        );
        const auto available = jmax<int64> (0, reader.lengthInSamples - sourceStart);
        const auto sourceSamples = static_cast<int> (
            jmin<int64> (requestedSourceSamples, available)
        );
        if (sourceSamples <= 0 || sourceSamples > scratch.getNumSamples())
            return;
        scratch.clear (0, sourceSamples);
        reader.read (&scratch, 0, sourceSamples, sourceStart, true, true);
        if (reader.numChannels == 1 && scratch.getNumChannels() > 1)
            scratch.copyFrom (1, 0, scratch, 0, 0, sourceSamples);

        for (int channel = 0; channel < destination.getNumChannels(); ++channel)
        {
            const auto sourceChannel = jmin (channel, scratch.getNumChannels() - 1);
            const auto* input = scratch.getReadPointer (sourceChannel);
            auto* output = destination.getWritePointer (channel, destinationOffset);
            for (int sample = 0; sample < samples; ++sample)
            {
                const auto sourcePosition = (
                    static_cast<double> (timelineSample + sample) * ratio
                    - static_cast<double> (sourceStart)
                );
                const auto index = static_cast<int> (std::floor (sourcePosition));
                if (index < 0 || index >= sourceSamples)
                {
                    output[sample] = 0.0f;
                    continue;
                }
                const auto nextIndex = jmin (index + 1, sourceSamples - 1);
                const auto fraction = static_cast<float> (sourcePosition - index);
                output[sample] = input[index] + fraction * (input[nextIndex] - input[index]);
            }
        }
    }

    void readTransportControl()
    {
        if (! transportControl.existsAsFile())
            return;
        String error;
        auto raw = readJsonFile (transportControl, error);
        auto* object = raw.getDynamicObject();
        if (object == nullptr || error.isNotEmpty())
            return;
        const auto revision = propertyInt (object, "revision", -1);
        if (revision == lastTransportRevision)
            return;
        lastTransportRevision = revision;
        if (propertyBool (object, "close_requested", false))
        {
            transportPlaying.store (false, std::memory_order_relaxed);
            outputEnabled.store (false, std::memory_order_relaxed);
            MessageManager::getInstance()->stopDispatchLoop();
            return;
        }
        const auto position = jmax (0.0, propertyDouble (object, "position_seconds", 0.0));
        const auto start = jmax (
            0.0,
            propertyDouble (object, "timeline_start", monitorTimelineStart.load())
        );
        const auto end = jmax (
            start,
            propertyDouble (object, "timeline_end", monitorTimelineEnd.load())
        );
        monitorTimelineStart.store (start, std::memory_order_relaxed);
        monitorTimelineEnd.store (end, std::memory_order_relaxed);
        const auto seekRevision = propertyInt (object, "seek_revision", -1);
        const auto nextPlaying = propertyBool (object, "playing", false)
            && propertyBool (object, "audible", true);
        outputEnabled.store (
            propertyBool (object, "output_enabled", false),
            std::memory_order_relaxed
        );
        const auto wasPlaying = transportPlaying.exchange (
            nextPlaying,
            std::memory_order_relaxed
        );
        if (seekRevision != lastSeekRevision || (nextPlaying && ! wasPlaying))
        {
            lastSeekRevision = seekRevision;
            const auto rate = activeSampleRate.load (std::memory_order_relaxed);
            transportSamplePosition.store (
                static_cast<int64> (std::llround (position * rate)),
                std::memory_order_relaxed
            );
            playHeadSamplePosition.store (
                static_cast<int64> (std::llround (position * rate)),
                std::memory_order_relaxed
            );
            transportEnded.store (false, std::memory_order_relaxed);
        }
        if (nextPlaying)
            silenceBlocksRemaining.store (0, std::memory_order_relaxed);
        else if (wasPlaying)
            silenceBlocksRemaining.store (
                jmax (
                    1,
                    roundToInt (
                        activeSampleRate.load() / static_cast<double> (activeBlockSize.load())
                    )
                ),
                std::memory_order_relaxed
            );
    }

    void flushState (bool capturePlugin)
    {
        if (plugin == nullptr)
            return;

        if (capturePlugin && processLock.tryEnter())
        {
            captureCachedPluginState();
            finalStateCaptured = true;
            processLock.exit();
        }

        auto monitor = jsonObject();
        const auto rate = activeSampleRate.load (std::memory_order_relaxed);
        setProperty (monitor, "ready", monitorReader != nullptr);
        setProperty (monitor, "realtime_ready", audioOutputReady.load() && bedReader != nullptr);
        setProperty (monitor, "audio_output_ready", audioOutputReady.load());
        setProperty (monitor, "effect_capable", effectCapable);
        setProperty (monitor, "playhead_ready", true);
        setProperty (monitor, "output_enabled", outputEnabled.load());
        setProperty (monitor, "playing", transportPlaying.load (std::memory_order_relaxed));
        setProperty (monitor, "ended", transportEnded.load (std::memory_order_relaxed));
        setProperty (monitor, "position_seconds", rate > 0.0
            ? static_cast<double> (transportSamplePosition.load()) / rate
            : 0.0);
        setProperty (monitor, "duration_seconds", projectDuration.load());
        setProperty (monitor, "blocks", monitorBlocks.load (std::memory_order_relaxed));
        setProperty (monitor, "peak", monitorPeak.load (std::memory_order_relaxed));
        setProperty (monitor, "output_peak", monitorOutputPeak.load (std::memory_order_relaxed));
        setProperty (monitor, "safety_bypassed", safetyBypassed.load());
        setProperty (
            monitor,
            "silent_output_ms",
            rate > 0.0
                ? 1000.0 * static_cast<double> (silentOutputSamples.load()) / rate
                : 0.0
        );
        setProperty (monitor, "device_name", audioDeviceName);
        setProperty (monitor, "sample_rate", rate);
        setProperty (monitor, "block_size", activeBlockSize.load());
        setProperty (monitor, "latency_samples", outputLatencySamples);
        setProperty (monitor, "latency_ms", rate > 0.0
            ? 1000.0 * static_cast<double> (outputLatencySamples) / rate
            : 0.0);
        setProperty (monitor, "xruns", deviceManager.getXRunCount());
        setProperty (monitor, "error", audioDeviceError);

        auto object = okObject();
        setProperty (
            object,
            "plugin",
            transportPlaying.load (std::memory_order_relaxed)
                ? lightweightPluginState()
                : cachedPlugin
        );
        setProperty (object, "monitor", monitor);
        stateOutput.getParentDirectory().createDirectory();
        stateOutput.replaceWithText (JSON::toString (object, true), false, false, "\n");
    }

    void refreshCachedParameterValues()
    {
        if (plugin == nullptr)
            return;
        if (auto* object = cachedPlugin.getDynamicObject())
            object->setProperty ("parameter_values", parameterValuesObject (*plugin));
    }

    void captureCachedPluginState()
    {
        refreshCachedParameterValues();
        if (plugin != nullptr)
            if (auto* object = cachedPlugin.getDynamicObject())
                object->setProperty ("state", captureState (*plugin));
    }

    var lightweightPluginState() const
    {
        auto lightweight = jsonObject();
        auto* source = cachedPlugin.getDynamicObject();
        if (source == nullptr)
            return lightweight;

        for (const auto* key : {
                 "name",
                 "descriptive_name",
                 "manufacturer",
                 "version",
                 "category",
                 "format",
                 "file",
                 "is_instrument",
                 "inputs",
                 "outputs"
             })
        {
            const Identifier identifier (key);
            setProperty (lightweight, identifier, source->getProperty (identifier));
        }
        return lightweight;
    }
};

int showEditor (const Request& request)
{
    auto realtimeRequest = request;
    {
        AudioDeviceManager probe;
        const auto error = probe.initialise (0, 2, nullptr, true);
        if (error.isEmpty())
            if (auto* device = probe.getCurrentAudioDevice())
            {
                realtimeRequest.sampleRate = device->getCurrentSampleRate();
                realtimeRequest.blockSize = jmax (256, device->getCurrentBufferSizeSamples());
            }
        probe.closeAudioDevice();
    }

    auto loaded = loadPlugin (realtimeRequest);
    if (loaded.instance == nullptr)
    {
        writeJsonStdout (errorObject (loaded.error));
        return 2;
    }

    preparePluginForStereo (
        *loaded.instance,
        realtimeRequest.sampleRate,
        realtimeRequest.blockSize
    );
    applyRequestSettings (*loaded.instance, realtimeRequest);

    std::unique_ptr<PluginEditorWindow> window (
        new PluginEditorWindow (
            std::move (loaded.instance),
            loaded.description,
            realtimeRequest
        )
    );

    MessageManager::getInstance()->runDispatchLoop();
    window.reset();
    return 0;
}

}
