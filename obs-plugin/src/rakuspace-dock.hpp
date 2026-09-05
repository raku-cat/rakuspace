#pragma once

namespace rakuspace {
// Creates the dock widget and registers it with obs_frontend_add_dock_by_id.
// Call once from obs_module_load, after the frontend is ready.
void register_dock();
// Opens the settings dialog, parented to the OBS main window. Safe to call
// from the Qt thread only (menu callback and the dock gear button both run there).
void open_settings_dialog();
}
