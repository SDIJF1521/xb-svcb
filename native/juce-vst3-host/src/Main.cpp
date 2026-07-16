#include <juce_audio_formats/juce_audio_formats.h>
#include <juce_audio_devices/juce_audio_devices.h>
#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_gui_extra/juce_gui_extra.h>

#include <cstdio>
#include <cstring>
#include <atomic>
#include <cmath>
#include <memory>

namespace
{
using namespace juce;

constexpr auto schemaName = "xb-svcb.juce-vst3-host.v1";
constexpr int protocolVersion = 1;

struct Request
{
    String command;
    File input;
    File output;
    File stateOutput;
    File monitorInput;
    File bedInput;
    File transportControl;
    File pluginPath;
    String pluginName;
    String state;
    var parameters;
    double sampleRate = 44100.0;
    double monitorTimelineStart = 0.0;
    double monitorTimelineEnd = 0.0;
    double projectDuration = 0.0;
    int blockSize = 128;
};

static String base64Encode (const void* data, size_t size)
{
    static constexpr char alphabet[] =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

    auto* bytes = static_cast<const unsigned char*> (data);
    String out;

    for (size_t i = 0; i < size; i += 3)
    {
        const auto b0 = bytes[i];
        const auto b1 = (i + 1 < size) ? bytes[i + 1] : 0;
        const auto b2 = (i + 2 < size) ? bytes[i + 2] : 0;

        out += alphabet[(b0 >> 2) & 0x3f];
        out += alphabet[((b0 & 0x03) << 4) | ((b1 >> 4) & 0x0f)];
        out += (i + 1 < size) ? alphabet[((b1 & 0x0f) << 2) | ((b2 >> 6) & 0x03)] : '=';
        out += (i + 2 < size) ? alphabet[b2 & 0x3f] : '=';
    }

    return out;
}

static MemoryBlock base64Decode (String text)
{
    text = text.retainCharacters ("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=");

    auto decode = [] (juce_wchar c) -> int
    {
        if (c >= 'A' && c <= 'Z') return static_cast<int> (c - 'A');
        if (c >= 'a' && c <= 'z') return static_cast<int> (c - 'a') + 26;
        if (c >= '0' && c <= '9') return static_cast<int> (c - '0') + 52;
        if (c == '+') return 62;
        if (c == '/') return 63;
        return 0;
    };

    MemoryBlock out;

    for (int i = 0; i < text.length(); i += 4)
    {
        const auto c0 = text[i];
        const auto c1 = (i + 1 < text.length()) ? text[i + 1] : '=';
        const auto c2 = (i + 2 < text.length()) ? text[i + 2] : '=';
        const auto c3 = (i + 3 < text.length()) ? text[i + 3] : '=';

        const auto b0 = decode (c0);
        const auto b1 = decode (c1);
        const auto b2 = decode (c2);
        const auto b3 = decode (c3);

        const unsigned char o0 = static_cast<unsigned char> ((b0 << 2) | (b1 >> 4));
        const unsigned char o1 = static_cast<unsigned char> (((b1 & 0x0f) << 4) | (b2 >> 2));
        const unsigned char o2 = static_cast<unsigned char> (((b2 & 0x03) << 6) | b3);

        out.append (&o0, 1);
        if (c2 != '=') out.append (&o1, 1);
        if (c3 != '=') out.append (&o2, 1);
    }

    return out;
}

static var jsonObject()
{
    return var (new DynamicObject());
}

static void setProperty (var& object, const Identifier& key, const var& value)
{
    if (auto* dynamic = object.getDynamicObject())
        dynamic->setProperty (key, value);
}

static var okObject()
{
    auto object = jsonObject();
    setProperty (object, "ok", true);
    setProperty (object, "schema", schemaName);
    setProperty (object, "protocol", protocolVersion);
    return object;
}

static var errorObject (String message)
{
    auto object = jsonObject();
    setProperty (object, "ok", false);
    setProperty (object, "schema", schemaName);
    setProperty (object, "protocol", protocolVersion);
    setProperty (object, "error", message);
    return object;
}

static void writeStdout (String text)
{
    const auto* bytes = text.toRawUTF8();
    std::fwrite (bytes, 1, std::strlen (bytes), stdout);
    std::fwrite ("\n", 1, 1, stdout);
    std::fflush (stdout);
}

static void writeJsonStdout (const var& object)
{
    writeStdout (JSON::toString (object, true));
}

static var readJsonFile (const File& file, String& error)
{
    if (! file.existsAsFile())
    {
        error = "Request file does not exist: " + file.getFullPathName();
        return {};
    }

    auto parsed = JSON::parse (file);
    if (! parsed.isObject())
        error = "Request file is not a JSON object";

    return parsed;
}

static String propertyString (DynamicObject* object, const Identifier& key, String fallback = {})
{
    if (object == nullptr)
        return fallback;
    auto value = object->getProperty (key);
    return value.isVoid() ? fallback : value.toString();
}

static double propertyDouble (DynamicObject* object, const Identifier& key, double fallback)
{
    if (object == nullptr)
        return fallback;
    auto value = object->getProperty (key);
    if (value.isVoid())
        return fallback;
    return static_cast<double> (value);
}

static int propertyInt (DynamicObject* object, const Identifier& key, int fallback)
{
    if (object == nullptr)
        return fallback;
    auto value = object->getProperty (key);
    if (value.isVoid())
        return fallback;
    return static_cast<int> (value);
}

static bool propertyBool (DynamicObject* object, const Identifier& key, bool fallback)
{
    if (object == nullptr)
        return fallback;
    auto value = object->getProperty (key);
    if (value.isVoid())
        return fallback;
    return static_cast<bool> (value);
}

static Request parseRequest (const var& raw)
{
    Request request;
    auto* root = raw.getDynamicObject();
    auto plugin = root != nullptr ? root->getProperty ("plugin") : var();
    auto* pluginObject = plugin.getDynamicObject();
    const auto inputPath = propertyString (root, "input");
    const auto outputPath = propertyString (root, "output");
    const auto stateOutputPath = propertyString (root, "state_output");
    const auto monitorInputPath = propertyString (root, "monitor_input");
    const auto bedInputPath = propertyString (root, "bed_input");
    const auto transportControlPath = propertyString (root, "transport_control");
    const auto pluginPath = propertyString (pluginObject, "path");

    request.command = propertyString (root, "command");
    request.input = inputPath.isNotEmpty() ? File (inputPath) : File();
    request.output = outputPath.isNotEmpty() ? File (outputPath) : File();
    request.stateOutput = stateOutputPath.isNotEmpty() ? File (stateOutputPath) : File();
    request.monitorInput = monitorInputPath.isNotEmpty() ? File (monitorInputPath) : File();
    request.bedInput = bedInputPath.isNotEmpty() ? File (bedInputPath) : File();
    request.transportControl = transportControlPath.isNotEmpty() ? File (transportControlPath) : File();
    request.sampleRate = jmax (8000.0, propertyDouble (root, "sample_rate", 44100.0));
    request.monitorTimelineStart = jmax (0.0, propertyDouble (root, "monitor_timeline_start", 0.0));
    request.monitorTimelineEnd = jmax (
        request.monitorTimelineStart,
        propertyDouble (root, "monitor_timeline_end", request.monitorTimelineStart)
    );
    request.projectDuration = jmax (0.0, propertyDouble (root, "project_duration", 0.0));
    request.blockSize = jlimit (32, 8192, propertyInt (root, "block_size", 128));
    request.pluginPath = pluginPath.isNotEmpty() ? File (pluginPath) : File();
    request.pluginName = propertyString (pluginObject, "name");
    request.state = propertyString (pluginObject, "state");
    request.parameters = pluginObject != nullptr ? pluginObject->getProperty ("parameters") : var();
    return request;
}

static String parameterId (AudioProcessorParameter& parameter, int index)
{
    if (auto* withId = dynamic_cast<AudioProcessorParameterWithID*> (&parameter))
        if (withId->paramID.isNotEmpty())
            return withId->paramID;

    return "p" + String (index);
}

static var parameterValuesObject (AudioProcessor& processor)
{
    auto object = jsonObject();
    auto params = processor.getParameters();

    for (int i = 0; i < params.size(); ++i)
    {
        if (auto* parameter = params[i])
            setProperty (object, parameterId (*parameter, i), parameter->getValue());
    }

    return object;
}

static var parameterList (AudioProcessor& processor)
{
    Array<var> list;
    auto params = processor.getParameters();

    for (int i = 0; i < params.size(); ++i)
    {
        auto* parameter = params[i];
        if (parameter == nullptr)
            continue;

        auto item = jsonObject();
        setProperty (item, "id", parameterId (*parameter, i));
        setProperty (item, "index", i);
        setProperty (item, "name", parameter->getName (128));
        setProperty (item, "label", parameter->getLabel());
        setProperty (item, "value", parameter->getValue());
        setProperty (item, "default", parameter->getDefaultValue());
        setProperty (item, "text", parameter->getText (parameter->getValue(), 128));
        setProperty (item, "steps", parameter->getNumSteps());
        setProperty (item, "discrete", parameter->isDiscrete());
        setProperty (item, "boolean", parameter->isBoolean());
        setProperty (item, "automatable", parameter->isAutomatable());
        list.add (item);
    }

    return var (list);
}

static String captureState (AudioProcessor& processor)
{
    MemoryBlock state;
    processor.getStateInformation (state);
    return base64Encode (state.getData(), state.getSize());
}

static void restoreState (AudioProcessor& processor, const String& encoded)
{
    if (encoded.isEmpty())
        return;

    auto state = base64Decode (encoded);
    if (state.getSize() > 0)
        processor.setStateInformation (state.getData(), static_cast<int> (state.getSize()));
}

static void applyParameters (AudioProcessor& processor, const var& rawParameters)
{
    auto* object = rawParameters.getDynamicObject();
    if (object == nullptr)
        return;

    auto params = processor.getParameters();
    auto& props = object->getProperties();

    for (int propertyIndex = 0; propertyIndex < props.size(); ++propertyIndex)
    {
        const auto key = props.getName (propertyIndex).toString();
        const auto value = props.getValueAt (propertyIndex);
        const auto normalized = jlimit (0.0f, 1.0f, static_cast<float> (static_cast<double> (value)));

        for (int i = 0; i < params.size(); ++i)
        {
            auto* parameter = params[i];
            if (parameter == nullptr)
                continue;

            if (key == parameterId (*parameter, i)
                || key == String (i)
                || key == parameter->getName (128))
            {
                parameter->setValueNotifyingHost (normalized);
                break;
            }
        }
    }
}

struct LoadedPlugin
{
    std::unique_ptr<AudioPluginInstance> instance;
    PluginDescription description;
    String error;
};

static LoadedPlugin loadPlugin (const Request& request)
{
    LoadedPlugin loaded;

    if (! request.pluginPath.exists())
    {
        loaded.error = "Plugin path does not exist: " + request.pluginPath.getFullPathName();
        return loaded;
    }

    AudioPluginFormatManager manager;
    addDefaultFormatsToManager (manager);
    OwnedArray<PluginDescription> descriptions;

    for (int i = 0; i < manager.getNumFormats(); ++i)
    {
        if (auto* format = manager.getFormat (i))
            format->findAllTypesForFile (descriptions, request.pluginPath.getFullPathName());
    }

    if (descriptions.isEmpty())
    {
        loaded.error = "No compatible plugin type found in: " + request.pluginPath.getFullPathName();
        return loaded;
    }

    loaded.description = *descriptions.getFirst();
    loaded.instance = manager.createPluginInstance (
        loaded.description,
        request.sampleRate,
        request.blockSize,
        loaded.error
    );

    if (loaded.instance == nullptr && loaded.error.isEmpty())
        loaded.error = "Plugin instance creation failed";

    if (loaded.instance != nullptr)
    {
        restoreState (*loaded.instance, request.state);
        applyParameters (*loaded.instance, request.parameters);
    }

    return loaded;
}

static void preparePluginForStereo (AudioPluginInstance& plugin, double sampleRate, int blockSize)
{
    AudioProcessor::BusesLayout layout;

    for (int i = 0; i < plugin.getBusCount (true); ++i)
        layout.inputBuses.add (i == 0 ? AudioChannelSet::stereo() : AudioChannelSet::disabled());

    for (int i = 0; i < plugin.getBusCount (false); ++i)
        layout.outputBuses.add (i == 0 ? AudioChannelSet::stereo() : AudioChannelSet::disabled());

    if (! layout.inputBuses.isEmpty() || ! layout.outputBuses.isEmpty())
        if (plugin.checkBusesLayoutSupported (layout))
            plugin.setBusesLayout (layout);

    plugin.setRateAndBufferSizeDetails (sampleRate, blockSize);
    plugin.prepareToPlay (sampleRate, blockSize);
    plugin.suspendProcessing (false);
}

static bool canProcessAudioEffect (
    const AudioPluginInstance& plugin,
    const PluginDescription& description
)
{
    return ! description.isInstrument
        && plugin.getTotalNumInputChannels() > 0
        && plugin.getTotalNumOutputChannels() > 0;
}

static var pluginMetadata (AudioPluginInstance& plugin, const PluginDescription& description)
{
    auto object = jsonObject();
    setProperty (object, "name", description.name);
    setProperty (object, "descriptive_name", description.descriptiveName);
    setProperty (object, "manufacturer", description.manufacturerName);
    setProperty (object, "version", description.version);
    setProperty (object, "category", description.category);
    setProperty (object, "format", description.pluginFormatName);
    setProperty (object, "file", description.fileOrIdentifier);
    setProperty (object, "uid", String (description.uniqueId));
    setProperty (object, "is_instrument", description.isInstrument);
    setProperty (object, "accepts_midi", description.isInstrument || plugin.acceptsMidi());
    setProperty (object, "produces_midi", plugin.producesMidi());
    setProperty (object, "has_editor", plugin.hasEditor());
    setProperty (object, "tail_seconds", plugin.getTailLengthSeconds());
    setProperty (object, "inputs", plugin.getTotalNumInputChannels());
    setProperty (object, "outputs", plugin.getTotalNumOutputChannels());
    setProperty (object, "parameters", parameterList (plugin));
    setProperty (object, "parameter_values", parameterValuesObject (plugin));
    setProperty (object, "state", captureState (plugin));
    return object;
}

static var pluginRuntimeMetadata (
    AudioPluginInstance& plugin,
    const PluginDescription& description
)
{
    auto object = jsonObject();
    setProperty (object, "name", description.name);
    setProperty (object, "descriptive_name", description.descriptiveName);
    setProperty (object, "manufacturer", description.manufacturerName);
    setProperty (object, "version", description.version);
    setProperty (object, "category", description.category);
    setProperty (object, "format", description.pluginFormatName);
    setProperty (object, "file", description.fileOrIdentifier);
    setProperty (object, "is_instrument", description.isInstrument);
    setProperty (object, "inputs", plugin.getTotalNumInputChannels());
    setProperty (object, "outputs", plugin.getTotalNumOutputChannels());
    setProperty (object, "parameter_values", parameterValuesObject (plugin));
    return object;
}

static bool writePluginStateFile (
    AudioPluginInstance& plugin,
    const PluginDescription& description,
    const File& file,
    const var& monitor = var()
)
{
    if (file.getFullPathName().isEmpty())
        return true;

    auto object = okObject();
    setProperty (object, "plugin", pluginMetadata (plugin, description));
    if (! monitor.isVoid())
        setProperty (object, "monitor", monitor);
    file.getParentDirectory().createDirectory();
    return file.replaceWithText (JSON::toString (object, true), false, false, "\n");
}

static int inspectPlugin (const Request& request)
{
    auto loaded = loadPlugin (request);
    if (loaded.instance == nullptr)
    {
        writeJsonStdout (errorObject (loaded.error));
        return 2;
    }

    preparePluginForStereo (*loaded.instance, request.sampleRate, request.blockSize);

    auto object = okObject();
    setProperty (object, "plugin", pluginMetadata (*loaded.instance, loaded.description));
    writeJsonStdout (object);

    loaded.instance->releaseResources();
    return 0;
}

static int renderPlugin (const Request& request)
{
    if (! request.input.existsAsFile())
    {
        writeJsonStdout (errorObject ("Input WAV does not exist: " + request.input.getFullPathName()));
        return 2;
    }

    if (request.output.getFullPathName().isEmpty())
    {
        writeJsonStdout (errorObject ("Output path is empty"));
        return 2;
    }

    auto loaded = loadPlugin (request);
    if (loaded.instance == nullptr)
    {
        writeJsonStdout (errorObject (loaded.error));
        return 2;
    }

    preparePluginForStereo (*loaded.instance, request.sampleRate, request.blockSize);
    if (! canProcessAudioEffect (*loaded.instance, loaded.description))
    {
        writeJsonStdout (errorObject (
            "Plugin is an instrument/MIDI plugin or has no usable audio input/output bus"
        ));
        loaded.instance->releaseResources();
        return 2;
    }

    AudioFormatManager formats;
    formats.registerBasicFormats();

    std::unique_ptr<AudioFormatReader> reader (formats.createReaderFor (request.input));
    if (reader == nullptr)
    {
        writeJsonStdout (errorObject ("Input audio could not be read"));
        return 2;
    }

    request.output.getParentDirectory().createDirectory();
    WavAudioFormat wav;
    std::unique_ptr<FileOutputStream> outputStream (request.output.createOutputStream());

    if (outputStream == nullptr)
    {
        writeJsonStdout (errorObject ("Output audio could not be opened"));
        return 2;
    }

    std::unique_ptr<AudioFormatWriter> writer (
        wav.createWriterFor (
            outputStream.release(),
            request.sampleRate,
            2,
            24,
            {},
            0
        )
    );

    if (writer == nullptr)
    {
        writeJsonStdout (errorObject ("Output WAV writer could not be created"));
        return 2;
    }

    const auto totalInputChannels = jmax (1, loaded.instance->getTotalNumInputChannels());
    const auto totalOutputChannels = jmax (2, loaded.instance->getTotalNumOutputChannels());
    const auto processChannels = jmax (2, jmax (totalInputChannels, totalOutputChannels));
    const auto totalSamples = reader->lengthInSamples;
    int64 position = 0;
    MidiBuffer midi;
    AudioBuffer<float> buffer (processChannels, request.blockSize);

    while (position < totalSamples)
    {
        const auto numThisBlock = static_cast<int> (jmin<int64> (request.blockSize, totalSamples - position));
        buffer.clear();
        reader->read (&buffer, 0, numThisBlock, position, true, true);

        if (reader->numChannels == 1 && processChannels > 1)
            buffer.copyFrom (1, 0, buffer, 0, 0, numThisBlock);

        loaded.instance->processBlock (buffer, midi);

        if (loaded.instance->getTotalNumOutputChannels() == 1 && processChannels > 1)
            buffer.copyFrom (1, 0, buffer, 0, 0, numThisBlock);

        if (! writer->writeFromAudioSampleBuffer (buffer, 0, numThisBlock))
        {
            writeJsonStdout (errorObject ("Output WAV write failed"));
            return 2;
        }

        position += numThisBlock;
    }

    writer.reset();
    writePluginStateFile (*loaded.instance, loaded.description, request.stateOutput);
    loaded.instance->releaseResources();

    auto object = okObject();
    setProperty (object, "output", request.output.getFullPathName());
    writeJsonStdout (object);
    return 0;
}

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

        if (request.monitorInput.existsAsFile())
        {
            AudioFormatManager formats;
            formats.registerBasicFormats();
            monitorReader.reset (formats.createReaderFor (request.monitorInput));
        }

        if (request.bedInput.existsAsFile())
        {
            AudioFormatManager formats;
            formats.registerBasicFormats();
            bedReader.reset (formats.createReaderFor (request.bedInput));
        }

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
        if (now - lastStateFlushMs >= 100)
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

static int showEditor (const Request& request)
{
    auto realtimeRequest = request;
    {
        AudioDeviceManager probe;
        const auto error = probe.initialise (0, 2, nullptr, true);
        if (error.isEmpty())
            if (auto* device = probe.getCurrentAudioDevice())
            {
                realtimeRequest.sampleRate = device->getCurrentSampleRate();
                realtimeRequest.blockSize = device->getCurrentBufferSizeSamples();
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

static int runHost (const StringArray& args)
{
    if (args.size() < 3)
    {
        writeJsonStdout (errorObject ("Usage: xb-juce-vst3-host <inspect|render|show-editor> <request.json>"));
        return 2;
    }

    const auto command = args[1];
    String parseError;
    auto raw = readJsonFile (File (args[2]), parseError);
    if (parseError.isNotEmpty())
    {
        writeJsonStdout (errorObject (parseError));
        return 2;
    }

    auto request = parseRequest (raw);
    if (request.command.isEmpty())
        request.command = command;

    ScopedJuceInitialiser_GUI juceInitialiser;

    if (command == "inspect")
        return inspectPlugin (request);

    if (command == "render")
        return renderPlugin (request);

    if (command == "show-editor")
        return showEditor (request);

    writeJsonStdout (errorObject ("Unknown command: " + command));
    return 2;
}

} // namespace

#if JUCE_WINDOWS
int wmain (int argc, wchar_t* argv[])
{
    juce::StringArray args;
    for (int i = 0; i < argc; ++i)
        args.add (juce::String (argv[i]));
    return runHost (args);
}
#else
int main (int argc, char* argv[])
{
    juce::StringArray args;
    for (int i = 0; i < argc; ++i)
        args.add (juce::String::fromUTF8 (argv[i]));
    return runHost (args);
}
#endif
