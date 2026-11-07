#pragma once

#include <juce_audio_processors/juce_audio_processors.h>

namespace xb::vst3
{
using namespace juce;

inline constexpr auto schemaName = "xb-svcb.juce-vst3-host.v1";
inline constexpr int protocolVersion = 1;

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

var jsonObject();
void setProperty(var& object, const Identifier& key, const var& value);
var okObject();
var errorObject(String message);
void writeJsonStdout(const var& object);
var readJsonFile(const File& file, String& error);
String propertyString(DynamicObject* object, const Identifier& key, String fallback = {});
double propertyDouble(DynamicObject* object, const Identifier& key, double fallback);
int propertyInt(DynamicObject* object, const Identifier& key, int fallback);
bool propertyBool(DynamicObject* object, const Identifier& key, bool fallback);
Request parseRequest(const var& raw);

String parameterId(AudioProcessorParameter& parameter, int index);
var parameterValuesObject(AudioProcessor& processor);
var parameterList(AudioProcessor& processor);
String captureState(AudioProcessor& processor);
void restoreState(AudioProcessor& processor, const String& encoded);
void applyParameters(AudioProcessor& processor, const var& rawParameters);
}
