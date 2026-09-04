#include "rakuspace-dock.hpp"

#include <obs-module.h>
#include <obs-frontend-api.h>

#include <QWidget>
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QPushButton>
#include <QLabel>
#include <QDialog>
#include <QMainWindow>

namespace rakuspace {

static QWidget *g_dock = nullptr;

void open_settings_dialog()
{
	auto *parent = static_cast<QWidget *>(obs_frontend_get_main_window());
	QDialog dlg(parent);
	dlg.setWindowTitle("RakuSpace Settings");
	auto *lay = new QVBoxLayout(&dlg);
	lay->addWidget(new QLabel("Settings land here in Task 2.", &dlg));
	auto *ok = new QPushButton("Close", &dlg);
	QObject::connect(ok, &QPushButton::clicked, &dlg, &QDialog::accept);
	lay->addWidget(ok);
	dlg.exec();
}

void register_dock()
{
	g_dock = new QWidget();
	g_dock->setObjectName("rakuspaceDock");

	auto *root = new QVBoxLayout(g_dock);

	auto *golive = new QPushButton("Go Live to RakuSpace", g_dock);
	golive->setEnabled(false);
	root->addWidget(golive);

	auto *status = new QLabel("Offline", g_dock);
	status->setObjectName("rakuspaceStatus");
	root->addWidget(status);

	auto *row = new QHBoxLayout();
	row->addStretch();
	auto *gear = new QPushButton("Settings", g_dock);
	QObject::connect(gear, &QPushButton::clicked, [] { open_settings_dialog(); });
	row->addWidget(gear);
	root->addLayout(row);

	root->addStretch();

	obs_frontend_add_dock_by_id("rakuspace_dock", "RakuSpace", g_dock);
}

} // namespace rakuspace
