#pragma once

#include "HostProtocol.h"

namespace xb::vst3
{
using namespace juce;

struct LoadedPlugin
{
    std::unique_ptr<AudioPluginInstance> instance;
    PluginDescription description;
    String error;
};

LoadedPlugin loadPlugin(const Request& request);
void applyRequestSettings(AudioProcessor& processor, const Request& request);
void preparePluginForStereo(AudioPluginInstance& plugin, double sampleRate, int blockSize);
bool canProcessAudioEffect(const AudioPluginInstance& plugin, const PluginDescription& description);
var pluginMetadata(AudioPluginInstance& plugin, const PluginDescription& description);
var pluginRuntimeMetadata(AudioPluginInstance& plugin, const PluginDescription& description);
bool writePluginStateFile(AudioPluginInstance& plugin, const PluginDescription& description,
                          const File& file, const var& monitor = var());
int inspectPlugin(const Request& request);
int renderPlugin(const Request& request);
}
