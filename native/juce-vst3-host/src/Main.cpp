#include "HostProtocol.h"
#include "PluginRuntime.h"
#include "PluginEditorWindow.h"
#include <juce_gui_extra/juce_gui_extra.h>

namespace xb::vst3
{
using namespace juce;

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


}

#if JUCE_WINDOWS
int wmain (int argc, wchar_t* argv[])
{
    juce::StringArray args;
    for (int i = 0; i < argc; ++i)
        args.add (juce::String (argv[i]));
    return xb::vst3::runHost (args);
}
#else
int main (int argc, char* argv[])
{
    juce::StringArray args;
    for (int i = 0; i < argc; ++i)
        args.add (juce::String::fromUTF8 (argv[i]));
    return xb::vst3::runHost (args);
}
#endif
