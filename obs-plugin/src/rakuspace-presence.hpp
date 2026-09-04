// rakuspace-presence.hpp
#pragma once
namespace rakuspace {
void presence_on_live();    // reads config, spawns the detached activity push
void presence_on_offline(); // clears the card, detached, bounded
}
