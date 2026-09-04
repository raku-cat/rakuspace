#include "rakuspace-dock.hpp"
#include "rakuspace-config-store.hpp"

#include <obs-module.h>
#include <obs-frontend-api.h>

#include <QWidget>
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QPushButton>
#include <QLabel>
#include <QDialog>
#include <QMainWindow>
#include <QLineEdit>
#include <QCheckBox>
#include <QFormLayout>
#include <QDialogButtonBox>

namespace rakuspace {

static QWidget *g_dock = nullptr;

void open_settings_dialog()
{
	auto *parent = static_cast<QWidget *>(obs_frontend_get_main_window());
	QDialog dlg(parent);
	dlg.setWindowTitle("RakuSpace Settings");

	Config c = load_config();

	auto *key = new QLineEdit(QString::fromStdString(c.stream_key), &dlg);
	key->setEchoMode(QLineEdit::Password);
	auto *user = new QLineEdit(QString::fromStdString(c.username), &dlg);
	auto *disc = new QCheckBox("Share status to Discord", &dlg);
	disc->setChecked(c.discord_enabled);
	auto *title = new QCheckBox("Include stream title", &dlg);
	title->setChecked(c.discord_include_title);
	auto *statusText =
		new QLineEdit(QString::fromStdString(c.discord_status_text), &dlg);

	auto sync = [&] {
		title->setEnabled(disc->isChecked());
		statusText->setEnabled(disc->isChecked());
	};
	QObject::connect(disc, &QCheckBox::toggled, &dlg, sync);
	sync();

	auto *form = new QFormLayout();
	form->addRow("Stream key", key);
	form->addRow("Username", user);
	form->addRow(disc);
	form->addRow(title);
	form->addRow("Status text", statusText);

	auto *bb = new QDialogButtonBox(
		QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dlg);
	QObject::connect(bb, &QDialogButtonBox::accepted, &dlg, &QDialog::accept);
	QObject::connect(bb, &QDialogButtonBox::rejected, &dlg, &QDialog::reject);

	auto *root = new QVBoxLayout(&dlg);
	root->addLayout(form);
	root->addWidget(bb);

	if (dlg.exec() != QDialog::Accepted)
		return;

	c.stream_key = key->text().toStdString();
	c.username = user->text().toStdString();
	c.discord_enabled = disc->isChecked();
	c.discord_include_title = title->isChecked();
	c.discord_status_text = statusText->text().toStdString();
	if (!save_config(c))
		blog(LOG_WARNING, "[rakuspace-obs] could not write config.json");
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
