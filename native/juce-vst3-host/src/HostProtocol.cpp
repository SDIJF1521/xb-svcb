#include "HostProtocol.h"

#include <cstdio>
#include <cstring>

namespace xb::vst3
{
using namespace juce;

namespace
{
String base64Encode(const void* data, size_t size)
{
    static constexpr char alphabet[] =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    const auto* bytes = static_cast<const unsigned char*>(data);
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

MemoryBlock base64Decode(String text)
{
    text = text.retainCharacters("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=");
    const auto decode = [](juce_wchar c) -> int
    {
        if (c >= 'A' && c <= 'Z') return static_cast<int>(c - 'A');
        if (c >= 'a' && c <= 'z') return static_cast<int>(c - 'a') + 26;
        if (c >= '0' && c <= '9') return static_cast<int>(c - '0') + 52;
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
        const auto b0 = decode(c0);
        const auto b1 = decode(c1);
        const auto b2 = decode(c2);
        const auto b3 = decode(c3);
        const unsigned char o0 = static_cast<unsigned char>((b0 << 2) | (b1 >> 4));
        const unsigned char o1 = static_cast<unsigned char>(((b1 & 0x0f) << 4) | (b2 >> 2));
        const unsigned char o2 = static_cast<unsigned char>(((b2 & 0x03) << 6) | b3);
        out.append(&o0, 1);
        if (c2 != '=') out.append(&o1, 1);
        if (c3 != '=') out.append(&o2, 1);
    }
    return out;
}

void writeStdout(String text)
{
    const auto* bytes = text.toRawUTF8();
    std::fwrite(bytes, 1, std::strlen(bytes), stdout);
    std::fwrite("\n", 1, 1, stdout);
    std::fflush(stdout);
}

}

String propertyString(DynamicObject* object, const Identifier& key, String fallback)
{
    if (object == nullptr) return fallback;
    const auto value = object->getProperty(key);
    return value.isVoid() ? fallback : value.toString();
}

double propertyDouble(DynamicObject* object, const Identifier& key, double fallback)
{
    if (object == nullptr) return fallback;
    const auto value = object->getProperty(key);
    return value.isVoid() ? fallback : static_cast<double>(value);
}

int propertyInt(DynamicObject* object, const Identifier& key, int fallback)
{
    if (object == nullptr) return fallback;
    const auto value = object->getProperty(key);
    return value.isVoid() ? fallback : static_cast<int>(value);
}

bool propertyBool(DynamicObject* object, const Identifier& key, bool fallback)
{
    if (object == nullptr) return fallback;
    const auto value = object->getProperty(key);
    return value.isVoid() ? fallback : static_cast<bool>(value);
}

var jsonObject()
{
    return var(new DynamicObject());
}

void setProperty(var& object, const Identifier& key, const var& value)
{
    if (auto* dynamic = object.getDynamicObject())
        dynamic->setProperty(key, value);
}

var okObject()
{
    auto object = jsonObject();
    setProperty(object, "ok", true);
    setProperty(object, "schema", schemaName);
    setProperty(object, "protocol", protocolVersion);
    return object;
}

var errorObject(String message)
{
    auto object = jsonObject();
    setProperty(object, "ok", false);
    setProperty(object, "schema", schemaName);
    setProperty(object, "protocol", protocolVersion);
    setProperty(object, "error", message);
    return object;
}

void writeJsonStdout(const var& object)
{
    writeStdout(JSON::toString(object, true));
}

var readJsonFile(const File& file, String& error)
{
    if (!file.existsAsFile())
    {
        error = "Request file does not exist: " + file.getFullPathName();
        return {};
    }
    auto parsed = JSON::parse(file);
    if (!parsed.isObject())
        error = "Request file is not a JSON object";
    return parsed;
}

Request parseRequest(const var& raw)
{
    Request request;
    auto* root = raw.getDynamicObject();
    const auto plugin = root != nullptr ? root->getProperty("plugin") : var();
    auto* pluginObject = plugin.getDynamicObject();
    const auto inputPath = propertyString(root, "input");
    const auto outputPath = propertyString(root, "output");
    const auto stateOutputPath = propertyString(root, "state_output");
    const auto monitorInputPath = propertyString(root, "monitor_input");
    const auto bedInputPath = propertyString(root, "bed_input");
    const auto transportControlPath = propertyString(root, "transport_control");
    const auto pluginPath = propertyString(pluginObject, "path");
    request.command = propertyString(root, "command");
    request.input = inputPath.isNotEmpty() ? File(inputPath) : File();
    request.output = outputPath.isNotEmpty() ? File(outputPath) : File();
    request.stateOutput = stateOutputPath.isNotEmpty() ? File(stateOutputPath) : File();
    request.monitorInput = monitorInputPath.isNotEmpty() ? File(monitorInputPath) : File();
    request.bedInput = bedInputPath.isNotEmpty() ? File(bedInputPath) : File();
    request.transportControl = transportControlPath.isNotEmpty() ? File(transportControlPath) : File();
    request.sampleRate = jmax(8000.0, propertyDouble(root, "sample_rate", 44100.0));
    request.monitorTimelineStart = jmax(0.0, propertyDouble(root, "monitor_timeline_start", 0.0));
    request.monitorTimelineEnd = jmax(request.monitorTimelineStart,
                                      propertyDouble(root, "monitor_timeline_end", request.monitorTimelineStart));
    request.projectDuration = jmax(0.0, propertyDouble(root, "project_duration", 0.0));
    request.blockSize = jlimit(32, 8192, propertyInt(root, "block_size", 128));
    request.pluginPath = pluginPath.isNotEmpty() ? File(pluginPath) : File();
    request.pluginName = propertyString(pluginObject, "name");
    request.state = propertyString(pluginObject, "state");
    request.parameters = pluginObject != nullptr ? pluginObject->getProperty("parameters") : var();
    return request;
}

String parameterId(AudioProcessorParameter& parameter, int index)
{
    if (auto* withId = dynamic_cast<AudioProcessorParameterWithID*>(&parameter))
        if (withId->paramID.isNotEmpty())
            return withId->paramID;
    return "p" + String(index);
}

var parameterValuesObject(AudioProcessor& processor)
{
    auto object = jsonObject();
    const auto params = processor.getParameters();
    for (int i = 0; i < params.size(); ++i)
        if (auto* parameter = params[i])
            setProperty(object, parameterId(*parameter, i), parameter->getValue());
    return object;
}

var parameterList(AudioProcessor& processor)
{
    Array<var> list;
    const auto params = processor.getParameters();
    for (int i = 0; i < params.size(); ++i)
    {
        auto* parameter = params[i];
        if (parameter == nullptr) continue;
        auto item = jsonObject();
        setProperty(item, "id", parameterId(*parameter, i));
        setProperty(item, "index", i);
        setProperty(item, "name", parameter->getName(128));
        setProperty(item, "label", parameter->getLabel());
        setProperty(item, "value", parameter->getValue());
        setProperty(item, "default", parameter->getDefaultValue());
        setProperty(item, "text", parameter->getText(parameter->getValue(), 128));
        setProperty(item, "steps", parameter->getNumSteps());
        setProperty(item, "discrete", parameter->isDiscrete());
        setProperty(item, "boolean", parameter->isBoolean());
        setProperty(item, "automatable", parameter->isAutomatable());
        list.add(item);
    }
    return var(list);
}

String captureState(AudioProcessor& processor)
{
    MemoryBlock state;
    processor.getStateInformation(state);
    return base64Encode(state.getData(), state.getSize());
}

void restoreState(AudioProcessor& processor, const String& encoded)
{
    if (encoded.isEmpty()) return;
    const auto state = base64Decode(encoded);
    if (state.getSize() > 0)
        processor.setStateInformation(state.getData(), static_cast<int>(state.getSize()));
}

void applyParameters(AudioProcessor& processor, const var& rawParameters)
{
    auto* object = rawParameters.getDynamicObject();
    if (object == nullptr) return;
    const auto params = processor.getParameters();
    auto& properties = object->getProperties();
    for (int propertyIndex = 0; propertyIndex < properties.size(); ++propertyIndex)
    {
        const auto key = properties.getName(propertyIndex).toString();
        const auto value = properties.getValueAt(propertyIndex);
        const auto normalized = jlimit(0.0f, 1.0f,
                                        static_cast<float>(static_cast<double>(value)));
        for (int i = 0; i < params.size(); ++i)
        {
            auto* parameter = params[i];
            if (parameter == nullptr) continue;
            if (key == parameterId(*parameter, i)
                || key == String(i)
                || key == parameter->getName(128))
            {
                parameter->setValueNotifyingHost(normalized);
                break;
            }
        }
    }
}
}
