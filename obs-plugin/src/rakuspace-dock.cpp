#include "rakuspace-dock.hpp"
#include "rakuspace-config-store.hpp"
#include "rakuspace-output.hpp"

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
#include <QObject>
#include <QTimer>
#include <QMetaObject>
#include <QElapsedTimer>
#include <QApplication>
#include <QPointer>
#include <QString>
#include <QChar>

namespace rakuspace {

static QWidget *g_dock = nullptr;

class DockController : public QObject {
	Q_OBJECT
public:
	QPointer<QPushButton> button;
	QPointer<QLabel> status;
	QTimer tick;
	QElapsedTimer since;
	bool live = false;
	bool reconnecting = false;

	DockController()
	{
		tick.setInterval(1000);
		connect(&tick, &QTimer::timeout, this,
			&DockController::refreshElapsed);
	}

public slots:
	void onToggle()
	{
		if (!button || !status)
			return;
		if (OutputManager::instance().active() || live) {
			OutputManager::instance().stop();
			return;
		}
		Config c = load_config();
		if (c.stream_key.empty()) {
			status->setText("Set your stream key in Settings");
			return;
		}
		button->setEnabled(false);
		status->setText("Connecting");
		if (!OutputManager::instance().start(c.stream_key)) {
			status->setText("Could not start, check the log");
			button->setEnabled(true);
		}
	}

	void onStarted()
	{
		if (!button || !status)
			return;
		live = true;
		reconnecting = false;
		since.start();
		tick.start();
		button->setText("Stop");
		button->setEnabled(true);
		refreshElapsed();
	}

	void onReconnecting()
	{
		reconnecting = true;
		if (status)
			status->setText("Reconnecting");
	}

	void onReconnectSuccess()
	{
		reconnecting = false;
		refreshElapsed();
	}

	void onStopped(int code)
	{
		if (!button || !status)
			return;
		live = false;
		reconnecting = false;
		tick.stop();
		button->setText("Go Live to RakuSpace");
		button->setEnabled(true);
		status->setText(code == 0 ? "Offline"
					  : "Offline, stream ended early");
	}

	void refreshElapsed()
	{
		if (!live || reconnecting || !status)
			return;
		qint64 s = since.elapsed() / 1000;
		status->setText(QString("Live %1:%2:%3")
					.arg(s / 3600, 2, 10, QChar('0'))
					.arg((s % 3600) / 60, 2, 10, QChar('0'))
					.arg(s % 60, 2, 10, QChar('0')));
	}
};

static DockController *g_ctl = nullptr;

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

	static DockController ctl;
	ctl.button = golive;
	ctl.status = status;
	g_ctl = &ctl;
	golive->setEnabled(true);
	QObject::connect(golive, &QPushButton::clicked, &ctl,
			 &DockController::onToggle);

	OutputManager::instance().set_callback([](OutputEvent ev, int code) {
		// libobs signal thread. Marshal to the Qt main thread. The
		// lambda captures nothing and reads the file scope g_ctl, which
		// is written once in register_dock on the Qt thread and read
		// only here on the Qt thread, so no lock is needed.
		if (!qApp)
			return;
		QMetaObject::invokeMethod(
			qApp,
			[ev, code] {
				if (!g_ctl)
					return;
				switch (ev) {
				case OutputEvent::Started:
					g_ctl->onStarted();
					break;
				case OutputEvent::Reconnecting:
					g_ctl->onReconnecting();
					break;
				case OutputEvent::ReconnectSuccess:
					g_ctl->onReconnectSuccess();
					break;
				case OutputEvent::Stopped:
					g_ctl->onStopped(code);
					break;
				}
			},
			Qt::QueuedConnection);
	});

	obs_frontend_add_dock_by_id("rakuspace_dock", "RakuSpace", g_dock);
}

} // namespace rakuspace

#include "rakuspace-dock.moc"
