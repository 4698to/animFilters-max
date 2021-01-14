#
# Copyright 2018 Michal Mach
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, see <http://www.gnu.org/licenses/>.

__version__ = '1.0'
__author__ = 'Michal Mach'

import sys
import os
import math
from functools import partial
from distutils.util import strtobool

import numpy as np
from PySide2 import QtCore
from PySide2 import QtWidgets
from PySide2 import QtUiTools
import shiboken2

import maya.cmds as cmds
import maya.OpenMayaUI as MayaUI
import maya.api.OpenMayaAnim as oma
import maya.api.OpenMaya as om
from scipy.signal import butter, filtfilt, medfilt

# Where is this script?
SCRIPT_LOC = os.path.split(__file__)[0]
print(SCRIPT_LOC)
maya_useNewAPI = True


def add_keys(anim_curve, key_dict):
	# type: (unicode, dict) -> None
	"""
	Add keyframes to animation curve

	:param anim_curve: animation curve name
	:param key_dict: dictionary of keyframes in {frame_number (float): value (float)} format
	:return: None
	"""

	unit = om.MTime.uiUnit()
	nodeNattr = cmds.listConnections(anim_curve, d=True, s=False, p=True)[0]
	selList = om.MSelectionList()
	selList.add(nodeNattr)
	mplug = selList.getPlug(0)
	dArrTimes = om.MTimeArray()
	dArrVals = om.MDoubleArray()

	if 'rotate' in nodeNattr:
		for i in key_dict.keys():
			dArrTimes.append(om.MTime(float(i), unit))
			dArrVals.append(om.MAngle.uiToInternal(key_dict[i]))
	else:
		for i in key_dict.keys():
			dArrTimes.append(om.MTime(float(i), unit))
			dArrVals.append(key_dict[i])

	crvFnc = oma.MFnAnimCurve(mplug)
	crvFnc.addKeys(dArrTimes, dArrVals, crvFnc.kTangentAuto, crvFnc.kTangentAuto)


def get_raw_curves():
	result_curves = {}
	anim_curves = cmds.keyframe(q=True, sl=True, name=True)
	if anim_curves is None:
		cmds.headsUpMessage("No animation keys/curve selected! Select keys to filter, please!")
		return None
	for anim_curve in anim_curves:
		anim_keys = cmds.keyframe(q=True, sl=True, timeChange=True)
		start, end = int(anim_keys[0]), int(anim_keys[len(anim_keys) - 1])
		anim_dict = {}
		for i in range(start, end + 1):
			anim_dict[i] = cmds.keyframe(anim_curve, q=True, time=(i, i), ev=True)[0]
		result_curves[anim_curve] = anim_dict
	#print(result_curves)
	#获取选择的动画曲线，逐帧
	return result_curves


def copy_original_curves():
	# type: () -> tuple
	"""
	Copy selected animation curves to clipboard and return theis names with start and end frames
	so we can paste them back later

	:return: list of anim curve names, start frame, end frame
	:rtype: list, float, float
	"""
	anim_curves = cmds.keyframe(q=True, sl=True, name=True)
	if anim_curves is None:
		cmds.headsUpMessage("No animation keys/curve selected! Select keys to filter, please!")
		return None, None, None
	anim_keys = cmds.keyframe(q=True, sl=True, timeChange=True)
	start, end = int(anim_keys[0]), int(anim_keys[len(anim_keys) - 1])
	cmds.copyKey(anim_curves, t=(start, end))
	return anim_curves, start, end


def paste_clipboard_curves(anim_curves, start, end):
	# type: (list, float, float) -> None
	"""
	Paste original anim curves we stored when the preview button was pressed

	:param anim_curves: list of animation curves
	:param start: start frame
	:param end: end frame
	:return: None
	"""
	cmds.pasteKey(anim_curves, t=(start, end), o="replace")


def median_filter(raw_anim_curves, window_size=15):
	if raw_anim_curves is None:
		cmds.headsUpMessage("No animation keys/curve selected! Select keys to filter, please!")
		return
	if window_size % 2 == 0:
		window_size += 1
	processed_curves = {}
	for key in raw_anim_curves.keys():
		start, end = min(raw_anim_curves[key]), max(raw_anim_curves[key])
		x = []
		for i in range(start, end):
			x.append(raw_anim_curves[key][i])
		y = medfilt(x, window_size)
		processed_keys = {}
		for i in range(start, end):
			processed_keys[str(i)] = y[i - start]
		processed_curves[key] = processed_keys
	return processed_curves


def butter_lowpass(cutoff, fs, order=5):
	nyq = 0.5 * fs
	# ensure cutoff frequency doesn't overflow sampling frequency
	if cutoff > nyq:
		cutoff = nyq
	normal_cutoff = cutoff / nyq
	b, a = butter(order, normal_cutoff, btype="low", analog=False)
	return b, a


def butter_lowpass_filter(data, cutoff, fs, order=5):
	b, a = butter_lowpass(cutoff, fs, order=order)
	padlen = 3 * max(len(a), len(b))

	# Switch padding method based on time range length
	if len(data) >= padlen:
		y = filtfilt(b, a, data)
	else:
		y = filtfilt(b, a, data, method="gust")
		cmds.warning("Working on a short segment, selecting longer time range could improve results.")
	return y


def butterworth_filter(raw_anim_curves, fs=30.0, cutoff=5.0, order=5):
	if raw_anim_curves is None:
		cmds.headsUpMessage("No animation keys/curve selected! Select keys to filter, please!")
		return

	processed_curves = {}
	for key in raw_anim_curves.keys():
		start, end = min(raw_anim_curves[key]), max(raw_anim_curves[key])
		x = []
		T = (end - start)
		nsamples = ((fs * T) / 30.0) + 1
		t_space = np.linspace(start, end, nsamples, endpoint=True)
		reached_end = False
		for t_sample in t_space:
			if int(t_sample) >= end and not reached_end:
				value = raw_anim_curves[key][int(t_sample)]
				reached_end = True
			else:
				value = raw_anim_curves[key][int(t_sample)] + (
						raw_anim_curves[key][int(t_sample) + 1] - raw_anim_curves[key][int(t_sample)]) * (
								t_sample - int(t_sample))
			x.append(value)
		y = butter_lowpass_filter(x, cutoff, fs, order)
		processed_keys = {}
		key_index = 0
		for t_sample in t_space:
			value = y[key_index]
			processed_keys[str(t_sample)] = value
			key_index += 1
		processed_curves[key] = processed_keys
	return processed_curves


def resample_keys(kv, thresh):
	start = float(min(kv.keys()))
	end = float(max(kv.keys()))
	startv = float(kv[start])
	endv = float(kv[end])
	total_error = 0
	offender = -1
	outlier = -1
	for k, v in kv.items():
		offset = (k - start) / (end - start)
		sample = (offset * endv) + ((1 - offset) * startv)
		delta = abs(v - sample)
		total_error += delta
		if delta > outlier:
			outlier = delta
			offender = k
	if total_error < thresh or len(kv.keys()) == 2:
		return [{start: startv, end: endv}]
	else:
		s1 = {kk: vv for kk, vv in kv.items() if kk <= offender}
		s2 = {kk: vv for kk, vv in kv.items() if kk >= offender}
		return resample_keys(s1, thresh) + resample_keys(s2, thresh)


def rejoin_keys(kvs):
	result = {}
	for item in kvs:
		result.update(item)
	return result


def decimate(keys, tolerance):
	return rejoin_keys(resample_keys(keys, tolerance))


def adaptive_filter(raw_anim_curves, tolerance_value):
	processed_curves = {}
	for key in raw_anim_curves.keys():
		processed_keys = decimate(raw_anim_curves[key], tolerance_value)
		processed_curves[key] = processed_keys
	return processed_curves


def apply_curves(original_curves, processed_curves=None):
	for curve_name in original_curves.keys():
		start, end = min(original_curves[curve_name]), max(original_curves[curve_name])
		cmds.cutKey(curve_name, time=(start + 0.001, end - 0.001), option="keys", cl=True)

		if processed_curves is not None:
			add_keys(curve_name, processed_curves[curve_name])
		else:
			add_keys(curve_name, original_curves[curve_name])


def select_curves(anim_curves, first_key_only=False):
	cmds.selectKey(cl=True)
	for curve_name in anim_curves.keys():
		start, end = min(anim_curves[curve_name]), max(anim_curves[curve_name])
		if first_key_only:
			cmds.selectKey(curve_name, t=(start, start), add=True)
		else:
			cmds.selectKey(curve_name, t=(start, end), add=True)


def loadAnimFiltersUI(uifilename, parent=None):
	"""Properly Loads and returns UI files - by BarryPye on stackOverflow"""
	loader = QtUiTools.QUiLoader()
	uifile = QtCore.QFile(uifilename)
	uifile.open(QtCore.QFile.ReadOnly)
	ui = loader.load(uifile, parent)
	uifile.close()
	return ui


class AnimFiltersUI(QtWidgets.QMainWindow):
	def __init__(self):
		mainUI = SCRIPT_LOC + "/animFilters.ui"
		MayaMain = shiboken2.wrapInstance(long(MayaUI.MQtUtil.mainWindow()), QtWidgets.QWidget)
		super(AnimFiltersUI, self).__init__(MayaMain)

		# main window load / settings
		self.MainWindowUI = loadAnimFiltersUI(mainUI, MayaMain)
		self.MainWindowUI.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
		self.MainWindowUI.destroyed.connect(self.onExitCode)
		self.MainWindowUI.show()

		# init settings
		script_name = os.path.basename(__file__)
		script_base, ext = os.path.splitext(script_name)  # extract basename and ext from filename
		self.settings = QtCore.QSettings("MayaAnimFilters", script_base)

		# connect sliders and spinners
		self.MainWindowUI.thresholdSlider.valueChanged.connect(
			partial(self.sliderChanged, self.MainWindowUI.thresholdSpinBox, 1000.0))
		self.MainWindowUI.thresholdSpinBox.valueChanged.connect(
			partial(self.spinBoxChanged, self.MainWindowUI.thresholdSlider, 1000.0))
		self.MainWindowUI.multiSlider.valueChanged.connect(
			partial(self.sliderChanged, self.MainWindowUI.multiSpinBox, 1.0))
		self.MainWindowUI.multiSpinBox.valueChanged.connect(
			partial(self.spinBoxChanged, self.MainWindowUI.multiSlider, 1.0))
		self.MainWindowUI.medianSlider.valueChanged.connect(
			partial(self.sliderChanged, self.MainWindowUI.medianSpinBox, 1.0))
		self.MainWindowUI.medianSpinBox.valueChanged.connect(
			partial(self.spinBoxChanged, self.MainWindowUI.medianSlider, 1.0))
		self.MainWindowUI.butterSampleFreqSlider.valueChanged.connect(
			partial(self.sliderChanged, self.MainWindowUI.butterSampleFreqSpinBox, 1.0))
		self.MainWindowUI.butterSampleFreqSpinBox.valueChanged.connect(
			partial(self.spinBoxChanged, self.MainWindowUI.butterSampleFreqSlider, 1.0))
		self.MainWindowUI.butterCutoffFreqSlider.valueChanged.connect(
			partial(self.sliderChanged, self.MainWindowUI.butterCutoffFreqSpinBox, 100.0))
		self.MainWindowUI.butterCutoffFreqSpinBox.valueChanged.connect(
			partial(self.spinBoxChanged, self.MainWindowUI.butterCutoffFreqSlider, 100.0))
		self.MainWindowUI.butterOrderSlider.valueChanged.connect(
			partial(self.sliderChanged, self.MainWindowUI.butterOrderSpinBox, 1.0))
		self.MainWindowUI.butterOrderSpinBox.valueChanged.connect(
			partial(self.spinBoxChanged, self.MainWindowUI.butterOrderSlider, 1.0))

		# connect buttons
		self.MainWindowUI.previewButton.clicked.connect(self.previewFilter)
		self.MainWindowUI.cancelButton.clicked.connect(self.cancelFilter)
		self.MainWindowUI.applyButton.clicked.connect(self.applyFilter)
		self.MainWindowUI.resetButton.clicked.connect(self.resetValues)
		self.MainWindowUI.bufferCurvesCheckBox.stateChanged.connect(self.bufferCurvesChanged)

		# initialize variables
		self.animCurvesBuffer = None
		self.animCurvesProcessed = None
		self.previewActive = False
		self.start = None
		self.end = None
		self.originalCurves = None
		self.bufferCurvesState = True
		self.restoreSettings()

	def restoreSettings(self):
		self.bufferCurvesState = self.settings.value("bufferCurves")

		# Is the tool ran for the first time? Store the initial checkbox value.
		if self.bufferCurvesState is None:
			self.bufferCurvesState = self.MainWindowUI.bufferCurvesCheckBox.isChecked()
			self.settings.setValue("bufferCurves", self.bufferCurvesState)
		else:
			self.MainWindowUI.bufferCurvesCheckBox.setChecked(strtobool(self.bufferCurvesState))

	def bufferCurvesChanged(self):
		self.bufferCurvesState = self.MainWindowUI.bufferCurvesCheckBox.isChecked()
		self.settings.setValue("bufferCurves", self.bufferCurvesState)

	def switchTabs(self, state=False):
		for i in range(0, self.MainWindowUI.tabWidget.count()):
			if not i == self.MainWindowUI.tabWidget.currentIndex():
				self.MainWindowUI.tabWidget.setTabEnabled(i, state)

	# switch state of buttons based on the Preview button state
	def switchButtons(self, state=True):
		self.MainWindowUI.previewButton.setEnabled(not state)
		self.MainWindowUI.cancelButton.setEnabled(state)
		self.MainWindowUI.applyButton.setEnabled(state)

	# update spin box value when slider changes
	def sliderChanged(self, target, multiplier, sliderValue):
		target.setValue(sliderValue / multiplier)
		if self.previewActive:
			self.refreshFilter()

	# update slider value when spin box value changes
	def spinBoxChanged(self, target, multiplier, spinBoxValue):
		target.setValue(spinBoxValue * multiplier)
		if self.previewActive:
			self.refreshFilter()

	# grab anim curves when the preview button is pressed
	def previewFilter(self):
		if self.bufferCurvesState is True:
			cmds.bufferCurve(animation='keys', overwrite=True)
		self.originalCurves, self.start, self.end = copy_original_curves()
		if self.originalCurves is None:
			return
		self.animCurvesBuffer = get_raw_curves()
		if self.animCurvesBuffer is None:
			return
		cmds.undoInfo(swf=False)
		self.MainWindowUI.statusBar().showMessage("UNDO suspended in preview mode!!")
		self.switchTabs(False)
		self.switchButtons(True)
		self.previewActive = True
		self.refreshFilter()

	def refreshFilter(self):
		if self.MainWindowUI.tabWidget.currentIndex() == 0:
			self.animCurvesProcessed = adaptive_filter(self.animCurvesBuffer,
													   self.MainWindowUI.thresholdSpinBox.value() *
													   self.MainWindowUI.multiSpinBox.value())
			apply_curves(self.animCurvesBuffer, self.animCurvesProcessed)
		elif self.MainWindowUI.tabWidget.currentIndex() == 1:
			self.animCurvesProcessed = butterworth_filter(self.animCurvesBuffer,
														  self.MainWindowUI.butterSampleFreqSpinBox.value(),
														  self.MainWindowUI.butterCutoffFreqSpinBox.value(),
														  self.MainWindowUI.butterOrderSpinBox.value())
			apply_curves(self.animCurvesBuffer, self.animCurvesProcessed)
		elif self.MainWindowUI.tabWidget.currentIndex() == 2:
			self.animCurvesProcessed = median_filter(self.animCurvesBuffer, self.MainWindowUI.medianSpinBox.value())
			apply_curves(self.animCurvesBuffer, self.animCurvesProcessed)
		select_curves(self.animCurvesProcessed, True)

	def resetValues(self):
		if self.MainWindowUI.tabWidget.currentIndex() == 0:
			self.MainWindowUI.multiSpinBox.setValue(0.5)
			self.MainWindowUI.thresholdSpinBox.setValue(0.5)
		elif self.MainWindowUI.tabWidget.currentIndex() == 1:
			self.MainWindowUI.butterSampleFreqSpinBox.setValue(30.0)
			self.MainWindowUI.butterCutoffFreqSpinBox.setValue(7.0)
			self.MainWindowUI.butterOrderSpinBox.setValue(5)
		elif self.MainWindowUI.tabWidget.currentIndex() == 2:
			self.MainWindowUI.medianSpinBox.setValue(35)

	def cancelFilter(self):
		paste_clipboard_curves(self.originalCurves, self.start, self.end)
		select_curves(self.animCurvesBuffer)
		self.switchButtons(False)
		self.switchTabs(True)
		self.animCurvesBuffer = None
		self.animCurvesProcessed = None
		self.previewActive = False
		cmds.undoInfo(swf=True)
		self.MainWindowUI.statusBar().showMessage("")

	def applyFilter(self):
		# apply original curve for undo step
		cmds.undoInfo(openChunk=True)
		try:
			apply_curves(self.animCurvesBuffer)
		finally:
			cmds.undoInfo(closeChunk=True)
		# apply processed curve for undo step
		cmds.undoInfo(swf=True)
		cmds.undoInfo(openChunk=True)
		try:
			apply_curves(self.animCurvesBuffer, self.animCurvesProcessed)
			select_curves(self.animCurvesBuffer)
		finally:
			cmds.undoInfo(closeChunk=True)
		self.switchButtons(False)
		self.switchTabs(True)
		self.animCurvesBuffer = None
		self.animCurvesProcessed = None
		self.previewActive = False
		self.MainWindowUI.statusBar().showMessage("")

	def onExitCode(self):
		if self.previewActive:
			apply_curves(self.animCurvesBuffer)
			select_curves(self.animCurvesBuffer)
		self.animCurvesBuffer = None
		self.animCurvesProcessed = None
		cmds.undoInfo(swf=True)


def main():
	"""Command within Maya to run this script"""
	if not (cmds.window("animFiltersWindow", exists=True)):
		AnimFiltersUI()
	else:
		sys.stdout.write("Tool is already open!\n")
