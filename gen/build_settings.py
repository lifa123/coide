# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'uis/build_settings.ui'
#
#
#
# WARNING! All changes made in this file will be lost!

from PyQt4 import QtCore, QtGui

try:
    _fromUtf8 = QtCore.QString.fromUtf8
except AttributeError:
    def _fromUtf8(s):
        return s

try:
    _encoding = QtGui.QApplication.UnicodeUTF8
    def _translate(context, text, disambig):
        return QtGui.QApplication.translate(context, text, disambig, _encoding)
except AttributeError:
    def _translate(context, text, disambig):
        return QtGui.QApplication.translate(context, text, disambig)

class Ui_BuildSettingsDialog(object):
    def setupUi(self, BuildSettingsDialog):
        BuildSettingsDialog.setObjectName(_fromUtf8("BuildSettingsDialog"))
        BuildSettingsDialog.resize(662, 459)
        BuildSettingsDialog.projTree = QtGui.QTreeWidget(BuildSettingsDialog)
        BuildSettingsDialog.projTree.setGeometry(QtCore.QRect(10, 10, 161, 341))
        BuildSettingsDialog.projTree.setHeaderHidden(True)
        BuildSettingsDialog.projTree.setObjectName(_fromUtf8("projTree"))
        BuildSettingsDialog.projTree.headerItem().setText(0, _fromUtf8("1"))
        BuildSettingsDialog.closeButton = QtGui.QPushButton(BuildSettingsDialog)
        BuildSettingsDialog.closeButton.setGeometry(QtCore.QRect(10, 420, 71, 27))
        BuildSettingsDialog.closeButton.setObjectName(_fromUtf8("closeButton"))
        BuildSettingsDialog.tabWidget = QtGui.QTabWidget(BuildSettingsDialog)
        BuildSettingsDialog.tabWidget.setGeometry(QtCore.QRect(192, 16, 449, 433))
        BuildSettingsDialog.tabWidget.setObjectName(_fromUtf8("tabWidget"))
        BuildSettingsDialog.tab = QtGui.QWidget()
        BuildSettingsDialog.tab.setObjectName(_fromUtf8("tab"))
        BuildSettingsDialog.tabWidget.addTab(BuildSettingsDialog.tab, _fromUtf8(""))
        BuildSettingsDialog.tab_2 = QtGui.QWidget()
        BuildSettingsDialog.tab_2.setObjectName(_fromUtf8("tab_2"))
        BuildSettingsDialog.tabWidget.addTab(BuildSettingsDialog.tab_2, _fromUtf8(""))
        BuildSettingsDialog.parallelCB = QtGui.QCheckBox(BuildSettingsDialog)
        BuildSettingsDialog.parallelCB.setGeometry(QtCore.QRect(10, 380, 141, 20))
        BuildSettingsDialog.parallelCB.setObjectName(_fromUtf8("parallelCB"))
        BuildSettingsDialog.symscanCB = QtGui.QCheckBox(BuildSettingsDialog)
        BuildSettingsDialog.symscanCB.setGeometry(QtCore.QRect(10, 360, 161, 20))
        BuildSettingsDialog.symscanCB.setObjectName(_fromUtf8("symscanCB"))
        BuildSettingsDialog.resetButton = QtGui.QPushButton(BuildSettingsDialog)
        BuildSettingsDialog.resetButton.setGeometry(QtCore.QRect(100, 420, 71, 27))
        BuildSettingsDialog.resetButton.setObjectName(_fromUtf8("resetButton"))

        self.retranslateUi(BuildSettingsDialog)
        QtCore.QMetaObject.connectSlotsByName(BuildSettingsDialog)

    def retranslateUi(self, BuildSettingsDialog):
        BuildSettingsDialog.setWindowTitle(_translate("BuildSettingsDialog", "Build Settings", None))
        BuildSettingsDialog.closeButton.setText(_translate("BuildSettingsDialog", "Close", None))
        BuildSettingsDialog.tabWidget.setTabText(BuildSettingsDialog.tabWidget.indexOf(BuildSettingsDialog.tab), _translate("BuildSettingsDialog", "Tab 1", None))
        BuildSettingsDialog.tabWidget.setTabText(BuildSettingsDialog.tabWidget.indexOf(BuildSettingsDialog.tab_2), _translate("BuildSettingsDialog", "Tab 2", None))
        BuildSettingsDialog.parallelCB.setText(_translate("BuildSettingsDialog", "Parallel Make", None))
        BuildSettingsDialog.symscanCB.setText(_translate("BuildSettingsDialog", "Symbol Scan", None))
        BuildSettingsDialog.resetButton.setText(_translate("BuildSettingsDialog", "Reset", None))

