#include "PluginRuntime.h"

#include <juce_audio_formats/juce_audio_formats.h>

namespace xb::vst3
{
using namespace juce;

LoadedPlugin loadPlugin(const Request& request)
{
    LoadedPlugin loaded;
    if (!request.pluginPath.exists())
    {
        loaded.error = "Plugin path does not exist: " + request.pluginPath.getFullPathName();
        return loaded;
    }

    AudioPluginFormatManager manager;
    addDefaultFormatsToManager(manager);
    OwnedArray<PluginDescription> descriptions;
    for (int i = 0; i < manager.getNumFormats(); ++i)
        if (auto* format = manager.getFormat(i))
            format->findAllTypesForFile(descriptions, request.pluginPath.getFullPathName());

    if (descriptions.isEmpty())
    {
        loaded.error = "No compatible plugin type found in: " + request.pluginPath.getFullPathName();
        return loaded;
    }

    loaded.description = *descriptions.getFirst();
    loaded.instance = manager.createPluginInstance(
        loaded.description, request.sampleRate, request.blockSize, loaded.error);
    if (loaded.instance == nullptr && loaded.error.isEmpty())
        loaded.error = "Plugin instance creation failed";
    return loaded;
}

void applyRequestSettings(AudioProcessor& processor, const Request& request)
{
    restoreState(processor, request.state);
    applyParameters(processor, request.parameters);
}

void preparePluginForStereo(AudioPluginInstance& plugin, double sampleRate, int blockSize)
{
    AudioProcessor::BusesLayout layout;
    for (int i = 0; i < plugin.getBusCount(true); ++i)
        layout.inputBuses.add(i == 0 ? AudioChannelSet::stereo() : AudioChannelSet::disabled());
    for (int i = 0; i < plugin.getBusCount(false); ++i)
        layout.outputBuses.add(i == 0 ? AudioChannelSet::stereo() : AudioChannelSet::disabled());

    if ((!layout.inputBuses.isEmpty() || !layout.outputBuses.isEmpty())
        && plugin.checkBusesLayoutSupported(layout))
        plugin.setBusesLayout(layout);

    plugin.setRateAndBufferSizeDetails(sampleRate, blockSize);
    plugin.prepareToPlay(sampleRate, blockSize);
    plugin.suspendProcessing(false);
}

bool canProcessAudioEffect(const AudioPluginInstance& plugin, const PluginDescription& description)
{
    return !description.isInstrument
        && plugin.getTotalNumInputChannels() > 0
        && plugin.getTotalNumOutputChannels() > 0;
}

var pluginMetadata(AudioPluginInstance& plugin, const PluginDescription& description)
{
    auto object = jsonObject();
    setProperty(object, "name", description.name);
    setProperty(object, "descriptive_name", description.descriptiveName);
    setProperty(object, "manufacturer", description.manufacturerName);
    setProperty(object, "version", description.version);
    setProperty(object, "category", description.category);
    setProperty(object, "format", description.pluginFormatName);
    setProperty(object, "file", description.fileOrIdentifier);
    setProperty(object, "uid", String(description.uniqueId));
    setProperty(object, "is_instrument", description.isInstrument);
    setProperty(object, "accepts_midi", description.isInstrument || plugin.acceptsMidi());
    setProperty(object, "produces_midi", plugin.producesMidi());
    setProperty(object, "has_editor", plugin.hasEditor());
    setProperty(object, "tail_seconds", plugin.getTailLengthSeconds());
    setProperty(object, "inputs", plugin.getTotalNumInputChannels());
    setProperty(object, "outputs", plugin.getTotalNumOutputChannels());
    setProperty(object, "parameters", parameterList(plugin));
    setProperty(object, "parameter_values", parameterValuesObject(plugin));
    setProperty(object, "state", captureState(plugin));
    return object;
}

var pluginRuntimeMetadata(AudioPluginInstance& plugin, const PluginDescription& description)
{
    auto object = jsonObject();
    setProperty(object, "name", description.name);
    setProperty(object, "descriptive_name", description.descriptiveName);
    setProperty(object, "manufacturer", description.manufacturerName);
    setProperty(object, "version", description.version);
    setProperty(object, "category", description.category);
    setProperty(object, "format", description.pluginFormatName);
    setProperty(object, "file", description.fileOrIdentifier);
    setProperty(object, "is_instrument", description.isInstrument);
    setProperty(object, "inputs", plugin.getTotalNumInputChannels());
    setProperty(object, "outputs", plugin.getTotalNumOutputChannels());
    setProperty(object, "parameter_values", parameterValuesObject(plugin));
    return object;
}

bool writePluginStateFile(AudioPluginInstance& plugin, const PluginDescription& description,
                          const File& file, const var& monitor)
{
    if (file.getFullPathName().isEmpty()) return true;
    auto object = okObject();
    setProperty(object, "plugin", pluginMetadata(plugin, description));
    if (!monitor.isVoid()) setProperty(object, "monitor", monitor);
    file.getParentDirectory().createDirectory();
    return file.replaceWithText(JSON::toString(object, true), false, false, "\n");
}

int inspectPlugin(const Request& request)
{
    auto loaded = loadPlugin(request);
    if (loaded.instance == nullptr)
    {
        writeJsonStdout(errorObject(loaded.error));
        return 2;
    }
    preparePluginForStereo(*loaded.instance, request.sampleRate, request.blockSize);
    applyRequestSettings(*loaded.instance, request);
    auto object = okObject();
    setProperty(object, "plugin", pluginMetadata(*loaded.instance, loaded.description));
    writeJsonStdout(object);
    loaded.instance->releaseResources();
    return 0;
}

int renderPlugin(const Request& request)
{
    if (!request.input.existsAsFile())
    {
        writeJsonStdout(errorObject("Input WAV does not exist: " + request.input.getFullPathName()));
        return 2;
    }
    if (request.output.getFullPathName().isEmpty())
    {
        writeJsonStdout(errorObject("Output path is empty"));
        return 2;
    }

    auto loaded = loadPlugin(request);
    if (loaded.instance == nullptr)
    {
        writeJsonStdout(errorObject(loaded.error));
        return 2;
    }
    preparePluginForStereo(*loaded.instance, request.sampleRate, request.blockSize);
    applyRequestSettings(*loaded.instance, request);
    if (!canProcessAudioEffect(*loaded.instance, loaded.description))
    {
        writeJsonStdout(errorObject("Plugin is an instrument/MIDI plugin or has no usable audio input/output bus"));
        loaded.instance->releaseResources();
        return 2;
    }

    AudioFormatManager formats;
    formats.registerBasicFormats();
    std::unique_ptr<AudioFormatReader> reader(formats.createReaderFor(request.input));
    if (reader == nullptr)
    {
        writeJsonStdout(errorObject("Input audio could not be read"));
        return 2;
    }

    request.output.getParentDirectory().createDirectory();
    WavAudioFormat wav;
    std::unique_ptr<FileOutputStream> outputStream(request.output.createOutputStream());
    if (outputStream == nullptr)
    {
        writeJsonStdout(errorObject("Output audio could not be opened"));
        return 2;
    }
    std::unique_ptr<AudioFormatWriter> writer(wav.createWriterFor(
        outputStream.release(), request.sampleRate, 2, 24, {}, 0));
    if (writer == nullptr)
    {
        writeJsonStdout(errorObject("Output WAV writer could not be created"));
        return 2;
    }

    const auto totalInputChannels = jmax(1, loaded.instance->getTotalNumInputChannels());
    const auto totalOutputChannels = jmax(2, loaded.instance->getTotalNumOutputChannels());
    const auto processChannels = jmax(2, jmax(totalInputChannels, totalOutputChannels));
    const auto totalSamples = reader->lengthInSamples;
    int64 position = 0;
    MidiBuffer midi;
    AudioBuffer<float> buffer(processChannels, request.blockSize);
    while (position < totalSamples)
    {
        const auto numThisBlock = static_cast<int>(jmin<int64>(request.blockSize, totalSamples - position));
        buffer.clear();
        reader->read(&buffer, 0, numThisBlock, position, true, true);
        if (reader->numChannels == 1 && processChannels > 1)
            buffer.copyFrom(1, 0, buffer, 0, 0, numThisBlock);
        loaded.instance->processBlock(buffer, midi);
        if (loaded.instance->getTotalNumOutputChannels() == 1 && processChannels > 1)
            buffer.copyFrom(1, 0, buffer, 0, 0, numThisBlock);
        if (!writer->writeFromAudioSampleBuffer(buffer, 0, numThisBlock))
        {
            writeJsonStdout(errorObject("Output WAV write failed"));
            return 2;
        }
        position += numThisBlock;
    }
    writer.reset();
    writePluginStateFile(*loaded.instance, loaded.description, request.stateOutput);
    loaded.instance->releaseResources();
    auto object = okObject();
    setProperty(object, "output", request.output.getFullPathName());
    writeJsonStdout(object);
    return 0;
}
}
