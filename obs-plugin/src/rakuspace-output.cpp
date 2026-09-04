#include "rakuspace-output.hpp"
#include "rakuspace-config.h"

#include <obs.h>
#include <obs-module.h>
#include <obs-frontend-api.h>
#include <util/config-file.h>
#include <util/platform.h>

#include <atomic>
#include <cstring>
#include <mutex>
#include <string>

namespace rakuspace {

// Resolve the encoder id the user has picked for streaming in the current
// profile. Simple mode maps a short name to a concrete id. Advanced mode
// stores the id directly. Falls back to "obs_x264".
static std::string resolve_stream_encoder_id()
{
	config_t *p = obs_frontend_get_profile_config();
	if (!p)
		return "obs_x264";

	const char *mode = config_get_string(p, "Output", "Mode");
	bool advanced = mode && (strcmp(mode, "Advanced") == 0 ||
				 strcmp(mode, "advanced") == 0);

	if (advanced) {
		const char *id = config_get_string(p, "AdvOut", "Encoder");
		if (id && *id)
			return id;
		return "obs_x264";
	}

	const char *simple = config_get_string(p, "SimpleOutput", "StreamEncoder");
	if (!simple)
		return "obs_x264";
	// OBS simple mode short names. Match get_simple_output_encoder() in OBS.
	if (strcmp(simple, "x264") == 0 || strcmp(simple, "x264_lowcpu") == 0)
		return "obs_x264";
	if (strcmp(simple, "nvenc") == 0)
		return "jim_nvenc";
	if (strcmp(simple, "nvenc_hevc") == 0)
		return "jim_hevc_nvenc";
	if (strcmp(simple, "nvenc_av1") == 0)
		return "jim_av1_nvenc";
	if (strcmp(simple, "qsv") == 0)
		return "obs_qsv11_v2";
	if (strcmp(simple, "qsv_av1") == 0)
		return "obs_qsv11_av1";
	if (strcmp(simple, "amd") == 0)
		return "h264_texture_amf";
	if (strcmp(simple, "amd_hevc") == 0)
		return "h265_texture_amf";
	if (strcmp(simple, "amd_av1") == 0)
		return "av1_texture_amf";
	if (strcmp(simple, "apple_h264") == 0)
		return "com.apple.videotoolbox.videoencoder.ave.avc";
	return "obs_x264";
}

// Build the video encoder settings. Simple mode: pull VBitrate and rate
// control from the profile. Advanced mode: load the profile's
// streamEncoder.json. Then force bf and bframes to 0.
static obs_data_t *build_video_settings()
{
	config_t *p = obs_frontend_get_profile_config();
	obs_data_t *v = nullptr;

	const char *mode = p ? config_get_string(p, "Output", "Mode") : nullptr;
	bool advanced = mode && (strcmp(mode, "Advanced") == 0 ||
				 strcmp(mode, "advanced") == 0);

	if (advanced) {
		char *dir = obs_frontend_get_current_profile_path();
		if (dir) {
			std::string path = std::string(dir) + "/streamEncoder.json";
			bfree(dir);
			v = obs_data_create_from_json_file(path.c_str());
		}
	}
	if (!v)
		v = obs_data_create();

	if (!advanced && p) {
		long long vb = config_get_int(p, "SimpleOutput", "VBitrate");
		if (vb <= 0)
			vb = 6000;
		obs_data_set_int(v, "bitrate", vb);
		if (!obs_data_has_user_value(v, "rate_control"))
			obs_data_set_string(v, "rate_control", "CBR");
	}
	if (!obs_data_has_user_value(v, "bitrate"))
		obs_data_set_int(v, "bitrate", 6000);

	// Our one enforcement. Nothing else on the encoder is touched.
	obs_data_set_int(v, "bf", 0);
	obs_data_set_int(v, "bframes", 0);
	blog(LOG_INFO, "[rakuspace-obs] B-frames set to 0 for OME low latency");

	return v;
}

static obs_data_t *build_audio_settings()
{
	config_t *p = obs_frontend_get_profile_config();
	obs_data_t *a = obs_data_create();
	long long ab = p ? config_get_int(p, "SimpleOutput", "ABitrate") : 160;
	if (ab <= 0)
		ab = 160;
	obs_data_set_int(a, "bitrate", ab);
	return a;
}

// The signal callbacks and the object reaper touch the private nested Impl,
// so they live as static members of Impl. The public hpp block stays as is.
struct OutputManager::Impl {
	std::mutex mtx;
	obs_output_t *output = nullptr;
	obs_service_t *service = nullptr;
	obs_encoder_t *venc = nullptr;
	obs_encoder_t *aenc = nullptr;
	std::mutex cb_mtx;   // guards cb only, never held with mtx
	OutputCallback cb;
	std::atomic<bool> running{false};

	static void fire(Impl *d, OutputEvent ev, int code);
	static void on_start(void *param, calldata_t *);
	static void on_stop(void *param, calldata_t *cd);
	static void on_reconnect(void *param, calldata_t *);
	static void on_reconnect_success(void *param, calldata_t *);
	static void stop_locked_impl(Impl *d);   // caller holds d->mtx
};

OutputManager &OutputManager::instance()
{
	static OutputManager m;
	if (!m.d)
		m.d = new Impl();
	return m;
}

void OutputManager::set_callback(OutputCallback cb)
{
	std::lock_guard<std::mutex> lk(d->cb_mtx);
	d->cb = std::move(cb);
}

bool OutputManager::active() const
{
	return d->running.load();
}

void OutputManager::Impl::fire(Impl *d, OutputEvent ev, int code)
{
	// Copy the callback under its own small lock, then invoke it with no
	// lock held. set_callback can run on the Qt thread while a libobs
	// signal thread is in here; d->mtx is deliberately not taken so the
	// lock order with stop()/shutdown() stays one way.
	OutputCallback cb;
	{
		std::lock_guard<std::mutex> lk(d->cb_mtx);
		cb = d->cb;
	}
	if (cb)
		cb(ev, code);
}

void OutputManager::Impl::on_start(void *param, calldata_t *)
{
	auto *d = static_cast<Impl *>(param);
	d->running.store(true);
	fire(d, OutputEvent::Started, 0);
}

void OutputManager::Impl::on_stop(void *param, calldata_t *cd)
{
	auto *d = static_cast<Impl *>(param);
	long long code = 0;
	calldata_get_int(cd, "code", &code);
	d->running.store(false);
	fire(d, OutputEvent::Stopped, (int)code);
}

void OutputManager::Impl::on_reconnect(void *param, calldata_t *)
{
	fire(static_cast<Impl *>(param), OutputEvent::Reconnecting, 0);
}

void OutputManager::Impl::on_reconnect_success(void *param, calldata_t *)
{
	fire(static_cast<Impl *>(param), OutputEvent::ReconnectSuccess, 0);
}

bool OutputManager::start(const std::string &stream_key)
{
	std::lock_guard<std::mutex> lk(d->mtx);
	if (d->output) {
		// A previous output that has finished but not yet been reaped
		// (graceful stop path). Release it now so the names are free.
		if (obs_output_active(d->output))
			return false;
		Impl::stop_locked_impl(d);
	}
	if (stream_key.empty()) {
		blog(LOG_WARNING, "[rakuspace-obs] stream key is empty");
		return false;
	}

	obs_data_t *svc_s = obs_data_create();
	obs_data_set_string(svc_s, "server", RAKUSPACE_RTMP_INGEST);
	obs_data_set_string(svc_s, "key", stream_key.c_str());
	obs_data_set_bool(svc_s, "use_auth", false);
	d->service = obs_service_create("rtmp_custom", "rakuspace_out_service",
				       svc_s, nullptr);
	obs_data_release(svc_s);
	if (!d->service) {
		blog(LOG_WARNING, "[rakuspace-obs] service create failed");
		return false;
	}

	std::string enc_id = resolve_stream_encoder_id();

	obs_data_t *v_s = build_video_settings();
	d->venc = obs_video_encoder_create(enc_id.c_str(), "rakuspace_venc",
					  v_s, nullptr);
	obs_data_release(v_s);
	if (!d->venc) {
		blog(LOG_WARNING, "[rakuspace-obs] video encoder %s failed, using obs_x264",
		     enc_id.c_str());
		obs_data_t *fx = obs_data_create();
		obs_data_set_int(fx, "bitrate", 6000);
		obs_data_set_string(fx, "rate_control", "CBR");
		obs_data_set_int(fx, "bf", 0);
		obs_data_set_int(fx, "bframes", 0);
		d->venc = obs_video_encoder_create("obs_x264", "rakuspace_venc",
						  fx, nullptr);
		obs_data_release(fx);
	}

	obs_data_t *a_s = build_audio_settings();
	d->aenc = obs_audio_encoder_create("ffmpeg_aac", "rakuspace_aenc",
					  a_s, 0, nullptr);
	obs_data_release(a_s);

	if (!d->venc || !d->aenc) {
		blog(LOG_WARNING, "[rakuspace-obs] encoder create failed, aborting start");
		Impl::stop_locked_impl(d);
		return false;
	}

	obs_encoder_set_video(d->venc, obs_get_video());
	obs_encoder_set_audio(d->aenc, obs_get_audio());

	d->output = obs_output_create("rtmp_output", "rakuspace_out",
				      nullptr, nullptr);
	if (!d->output) {
		blog(LOG_WARNING, "[rakuspace-obs] output create failed");
		Impl::stop_locked_impl(d);
		return false;
	}
	obs_output_set_service(d->output, d->service);
	obs_output_set_video_encoder(d->output, d->venc);
	obs_output_set_audio_encoder(d->output, d->aenc, 0);
	obs_output_set_reconnect_settings(d->output, 20, 10);  // retries, sec

	signal_handler_t *sh = obs_output_get_signal_handler(d->output);
	signal_handler_connect(sh, "start", Impl::on_start, d);
	signal_handler_connect(sh, "stop", Impl::on_stop, d);
	signal_handler_connect(sh, "reconnect", Impl::on_reconnect, d);
	signal_handler_connect(sh, "reconnect_success",
			       Impl::on_reconnect_success, d);

	if (!obs_output_start(d->output)) {
		const char *err = obs_output_get_last_error(d->output);
		blog(LOG_WARNING, "[rakuspace-obs] output start failed: %s",
		     err ? err : "unknown");
		Impl::stop_locked_impl(d);
		return false;
	}
	return true;
}

// caller holds d->mtx
void OutputManager::Impl::stop_locked_impl(Impl *d)
{
	if (d->output) {
		signal_handler_t *sh = obs_output_get_signal_handler(d->output);
		signal_handler_disconnect(sh, "start", on_start, d);
		signal_handler_disconnect(sh, "stop", on_stop, d);
		signal_handler_disconnect(sh, "reconnect", on_reconnect, d);
		signal_handler_disconnect(sh, "reconnect_success",
					  on_reconnect_success, d);
		obs_output_stop(d->output);
		obs_output_release(d->output);
		d->output = nullptr;
	}
	if (d->venc) {
		obs_encoder_release(d->venc);
		d->venc = nullptr;
	}
	if (d->aenc) {
		obs_encoder_release(d->aenc);
		d->aenc = nullptr;
	}
	if (d->service) {
		obs_service_release(d->service);
		d->service = nullptr;
	}
	d->running.store(false);
}

void OutputManager::stop()
{
	std::lock_guard<std::mutex> lk(d->mtx);
	if (d->output && obs_output_active(d->output)) {
		obs_output_stop(d->output);   // graceful, on_stop clears state
		return;
	}
	Impl::stop_locked_impl(d);
}

void OutputManager::shutdown()
{
	std::lock_guard<std::mutex> lk(d->mtx);
	if (d->output && obs_output_active(d->output)) {
		obs_output_stop(d->output);
		for (int i = 0; i < 200 && obs_output_active(d->output); ++i)
			os_sleep_ms(10);
		obs_output_force_stop(d->output);
	}
	Impl::stop_locked_impl(d);
}

}
