#pragma once
#include <functional>
#include <string>

namespace rakuspace {

enum class OutputEvent { Started, Stopped, Reconnecting, ReconnectSuccess };

// cb is invoked from libobs signal threads, not the Qt thread. The receiver
// marshals to the UI thread. `code` is meaningful only for Stopped: 0 is a
// clean stop, non zero is an error stop (already gave up on reconnect).
using OutputCallback = std::function<void(OutputEvent ev, int code)>;

class OutputManager {
public:
	static OutputManager &instance();

	void set_callback(OutputCallback cb);   // Qt thread, before start

	// Builds service, encoders, output and starts. Returns false if it could
	// not even begin (empty key, encoder create failure). A true return does
	// not mean connected, the Started event does.
	bool start(const std::string &stream_key);

	void stop();                            // async, the Stopped event follows
	void reap();                            // release a finished output, no event
	bool active() const;

	void shutdown();                        // obs_module_unload, blocking

private:
	OutputManager() = default;
	struct Impl;
	Impl *d = nullptr;
};

}
