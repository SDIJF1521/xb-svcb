#include <juce_audio_formats/juce_audio_formats.h>
#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_gui_extra/juce_gui_extra.h>

#include <cstdio>
#include <cstring>
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
    File pluginPath;
    String pluginName;
    String state;
    var parameters;
    double sampleRate = 44100.0;
    int blockSize = 512;
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

static Request parseRequest (const var& raw)
{
    Request request;
    auto* root = raw.getDynamicObject();
    auto plugin = root != nullptr ? root->getProperty ("plugin") : var();
    auto* pluginObject = plugin.getDynamicObject();
    const auto inputPath = propertyString (root, "input");
    const auto outputPath = propertyString (root, "output");
    const auto stateOutputPath = propertyString (root, "state_output");
    const auto pluginPath = propertyString (pluginObject, "path");

    request.command = propertyString (root, "command");
    request.input = inputPath.isNotEmpty() ? File (inputPath) : File();
    request.output = outputPath.isNotEmpty() ? File (outputPath) : File();
    request.stateOutput = stateOutputPath.isNotEmpty() ? File (stateOutputPath) : File();
    request.sampleRate = jmax (8000.0, propertyDouble (root, "sample_rate", 44100.0));
    request.blockSize = jlimit (32, 8192, propertyInt (root, "block_size", 512));
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

static bool writePluginStateFile (AudioPluginInstance& plugin, const PluginDescription& description, const File& file)
{
    if (file.getFullPathName().isEmpty())
        return true;

    auto object = okObject();
    setProperty (object, "plugin", pluginMetadata (plugin, description));
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

    preparePluginForStereo (*loaded.instance, request.sampleRate, request.blockSize);

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
                                 private Timer
{
public:
    PluginEditorWindow (
        std::unique_ptr<AudioPluginInstance> pluginInstance,
        PluginDescription pluginDescription,
        File stateOutputFile
    )
        : DocumentWindow (
            pluginDescription.name.isNotEmpty() ? pluginDescription.name : "VST3 Plugin",
            Colours::black,
            DocumentWindow::closeButton | DocumentWindow::minimiseButton
          ),
          plugin (std::move (pluginInstance)),
          description (std::move (pluginDescription)),
          stateOutput (std::move (stateOutputFile))
    {
        setUsingNativeTitleBar (true);
        setResizable (true, true);

        std::unique_ptr<AudioProcessorEditor> editor (plugin->createEditorIfNeeded());
        if (editor == nullptr)
            editor.reset (new GenericAudioProcessorEditor (*plugin));

        auto width = jmax (420, editor->getWidth());
        auto height = jmax (260, editor->getHeight());
        setContentOwned (editor.release(), true);
        centreWithSize (width, height);
        setVisible (true);

        flushState();
        startTimer (700);
    }

    ~PluginEditorWindow() override
    {
        stopTimer();
        flushState();
        clearContentComponent();
    }

    void closeButtonPressed() override
    {
        flushState();
        stopTimer();
        MessageManager::getInstance()->stopDispatchLoop();
    }

private:
    std::unique_ptr<AudioPluginInstance> plugin;
    PluginDescription description;
    File stateOutput;

    void timerCallback() override
    {
        flushState();
    }

    void flushState()
    {
        if (plugin != nullptr)
            writePluginStateFile (*plugin, description, stateOutput);
    }
};

static int showEditor (const Request& request)
{
    auto loaded = loadPlugin (request);
    if (loaded.instance == nullptr)
    {
        writeJsonStdout (errorObject (loaded.error));
        return 2;
    }

    preparePluginForStereo (*loaded.instance, request.sampleRate, request.blockSize);

    std::unique_ptr<PluginEditorWindow> window (
        new PluginEditorWindow (
            std::move (loaded.instance),
            loaded.description,
            request.stateOutput
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
