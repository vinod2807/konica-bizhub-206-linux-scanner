******************************************************************

Printer (GDI) Driver and Scan Driver for Windows Vista, Server 2008, Server 2008 R2, 7, Server 2012, Server 2012 R2, 8.1 and 10

******************************************************************
******************************************************************

This README file includes the following information.

1. System Requirements
2. Installation using installer
    2.1 For USB connection
    2.2 For network connection
3. Uninstalling the printer driver and scan driver
    3.1 Uninstall printer driver
    3.2 Uninstall scan driver (TWAIN/WIA)
4. Release Note
    4.1 How to display the "300 DPI" on the Adobe Acrobat.

******************************************************************
Any processor of the same or higher specifications as recommended for your operating system.

1. System Requirements
    The following are operating environmental requirements for using the printer/scanner driver.
    * CPU
        Any processor of the same or higher specifications as recommended for your operating system.
    * Operating system
        Windows Vista (x86/x64)
        Windows Server 2008 (x86/x64)
        Windows Server 2008 R2 (x64)
        Windows 7 (x86/x64)
        Windows Server 2012 (x64)
        Windows Server 2012 R2 (x64)
        Windows 8.1 (x86/x64)
        Windows 10 (x86/x64)
    * Memory
        Memory capacity as recommended for your operating system.
        Sufficient memory resource is required for your operating system and the applications to be used.
    * Interface
        Ethernet 10Base-T/100Base-TX
        USB port compatible with USB Revision 2.0
    * Driver
        CD-ROM drive

     Reference
     - Select the page description language according to the application used for printing.
     - Either of the installer or Add Printer Wizard can be used to install the printer driver.
     - For network connection, optional Image Controller IC-209 or Network Card NC-504 is required.



2. Installation using installer
   The installer automatically detects the printer on the same TCP/IP network as your computer or the machine
   connected via USB to your computer, and allows you to install the required printer driver. You can also install
   the printer driver by manually specifying the connection destination.

   Reference
   - Administrator authority is required for installation.
   - If a wizard window for adding new hardware opens when using USB connection, click [Cancel].
   - When you install the printer driver, WIA and TWAIN scan drivers are installed at the same time.

2.1 For USB connection
    The USB cable must be connected during the last installation step. Do not connect the USB cable to this
    machine until a message appears on the screen instructing you to connect the cable.
(1) Insert the printer driver CD-ROM into the CD-ROM drive of the computer.
     *The required CD-ROM varies depending on the printer driver. Select the CD-ROM corresponding
     to the printer driver used.
(2) Open the printer driver folder on the CD-ROM, and double-click [Setup.exe].
     *If the [User Account Control] screen appears, click [Continue] or [Yes].
     The installer starts.
(3) Select a language, then click [OK].
(4) Click [Next].
(5) After checking all terms in the license agreement, select [I accept the terms of the License Agreement],
     then click [Next].
     *If you disagree, you will not be able to install the driver.
(6) Select this machine in [Select Model].
(7) Select port [USB] to connect, then click [Next].
     When the Verify the publisher dialog box of [Windows Security] appears, click [Install this driver software anyway].
     The installation starts.
(8) When a message appears instructing you to connect the USB cable, connect the USB cable between
     the computer and this machine.
     *If the window instructing you to connect the USB cable does not appear, operate according to the
     instructions on the currently displayed window.
(9) Click [Finish].

2.2 For network connection
    To use this machine as part of a network, connect the computer with this machine via the network and check
    the IP address and RAW port number (initial setting: [9100]) before installing the printer driver.

    Reference
    The IP address and RAW port number can be checked in [IPv4 Configuration]. For details on the network
    settings, refer to "Network settings" of [User's Guide Network Administrator], and PageScope Web Connection
    - [Network] - [TCP/IP Configuration] and [Network]-[IPv4 Configuration].

(1) Insert the printer driver CD-ROM into the CD-ROM drive of the computer.
     *The required CD-ROM varies depending on the printer driver. Select the CD-ROM corresponding
     to the printer driver used.
(2) Open the printer driver folder on the CD-ROM, and double-click [Setup.exe].
     *If the [User Account Control] screen appears, click [Continue] or [Yes].
     The installer starts.
(3) Select a language, then click [OK].
(4) Click [Next].
(5) After checking all terms in the license agreement, select [I accept the terms of the License Agreement],
     then click [Next].
     *If you disagree, you will not be able to install the driver.
(6) Select this machine in [Select Model].
(7) Select port [Network] to connect, and click [Search].
    The connected machine is automatically detected.
(8) Select the IP address of the machine, then click [OK].
(9) Click [Next].
     *If the machine is not detected by [Search], you can enter the IP address directly.
     When the Verify the publisher dialog box of [Windows Security] appears, click [Install this driver software anyway].
     The installation starts.
(10)Click [Finish].



3. Uninstalling the printer driver and scanner driver
   This chapter describes the procedure for uninstalling the printer driver.
   When you have to remove the printer driver, for example, when reinstallation of the printer driver is necessary,
   remove the driver using the following procedure.

3.1 Uninstall printer driver
    Remove the printer driver manually.
(1) Open the [Printers], [Devices and Printers], or [Printers and Faxes] window.
(2) Select the icon for the printer to be uninstalled.
(3) Remove the printer driver.
     *In Windows Vista/Server 2008, press the Delete key on the computer keyboard.
     *In Windows Server 2008 R2/7/Server 2012/Server 2012 R2/8.1/10, click [Remove device] on the toolbar.
(4) From then on, follow the instructions on the pages that follow.
     When removal is completed, the icon will disappear in the [Printers], [Devices and Printers], or [Printers and Faxes] window.
     Go on to remove the printer driver from the server properties.
(5) Open the [Server Properties].
     *In Windows Vista/Server 2008, right-click on the area that has nothing displayed in the [Printers]
     window, then click [Run as administrator] - [Server Properties].
     *In Windows Server 2008 R2/7/Server 2012/Server 2012 R2/8.1/10, select other printer, then click [Print Server Properties] on the toolbar.
     *If the [User Account Control] window appears, click [Continue] or [Yes].
(6) Click the [Drivers] tab.
     *In Windows 7/8.1/10, click [Change Form Settings] located in the lower left corner of the window to run as the administrator authority.
(7) From the [Installed printer drivers:] list, select the printer driver to be removed, and then click [Remove...].
(8) In a window confirming the target to be removed, select [Remove driver only.] or [Remove driver and driver package.], then click [OK].
(9) In the dialog box for confirming whether you are sure to remove the target, click [Yes].
     The dialog box to confirm whether you are sure you want to remove the target appears. Click [Delete].
(10)Close the open windows, and then restart the computer.
     *Be sure to restart the computer.
     This completes removing the printer driver.

3.2 Uninstall scan driver (TWAIN/WIA)
(1) Click [Start], then click [All Program].
(2) Click [KONICA MINOLTA XXX Scanner], then click [UnInstScan].
    *If User Account Control screen is displayed, click [Yes].
    Uninstall Wizard starts.
(3) Click [Next].
    A confirmation dialog box appears.
(4) Click [Yes].
    The completion screen appears when the driver has been deleted.
(5) Click [Finish].



4. Release Note

4.1 How to display "300 DPI" on Adobe Acrobat
    When the TWAIN driver on Adobe Acrobat has no "300 DPI" in the "Resolution" menu, 
   "300 DPI" is enabled by the following procedures.
(1) Adobe Acrobat 8
    (1-1) Select "From Scanner..." of the "Create PDF" pull-down menu.
    (1-2) Select "Please select a device" in the "Scanner" menu.
    (1-3) Select your TWAIN driver.
    (1-4) Click the "Scanner Options..." button to display the "Scanner Options..." dialog.
    (1-5) Select "Show Scanner's Native Interface" in the "User Interface" pull-down menu.
    (1-6) Click the "Scan" button.

(2) Adobe Acrobat 9 or X
    (2-1) Click the "Defaults" button on the property.
    (2-2) Select "Please select a device" in the "Scanner" menu.
    (2-3) Select your TWAIN driver again.



Microsoft and Windows are either registered trademarks or trademarks of Microsoft Corporation 
in the United States and/or other countries.
Adobe and Acrobat are either registered trademarks or trademarks of Adobe Systems Incorporated 
in the United States and/or other countries.
All other product and brand names are trademarks or registered trademarks of their respective companies or
organizations.