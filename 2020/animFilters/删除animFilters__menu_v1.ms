python.Init()
(
	if ((menuMan.findMenu "animFilters") != undefined) then
	(
		menuMan.unRegisterMenu (menuMan.findMenu "animFilters")
		menuMan.updateMenuBar()
	)

)
