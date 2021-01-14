(
	if ((menuMan.findMenu "animFilters") != undefined) then
	(
		menuMan.unRegisterMenu (menuMan.findMenu "animFilters")
		menuMan.updateMenuBar()
	)


	macroScript animFilters_max category:"animFilters" buttonText: "animFilters_v1"
	(
		python.ExecuteFile((getDir #scripts) + "\\animFilters\\animFilters_2020max.py")
	)
	


	Main = menuMan.getMainMenuBar()
	Menu = menuMan.createMenu "animFilters"
	theSubMenu = menuMan.createSubMenuItem "animFilters" Menu
	Main.addItem theSubMenu (Main.numItems()+1)

	Action = menuMan.createActionItem "animFilters_max" "animFilters"
	Menu.addItem Action (Menu.numItems() + 1 )
	
	menuMan.updateMenuBar()
)
