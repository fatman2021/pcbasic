#!/bin/sh
# PC-BASIC install/uninstall script for Linux

SCRIPT=$0
SPAWNED=$1

do_close () {
    if [ "$SPAWNED" = "spawned" ]; then
        echo "Press ENTER to exit."
        read KEY
    fi
    exit 0
}

abort () {
    echo "Installation aborted. No changes were made."
    do_close
}

check_permissions () {
    if [ ! -w $(dirname $INSTALL_DIR) ]; then
        echo
        echo -n "ERROR: You do not have permission to write to "
        dirname $INSTALL_DIR
        abort 
    fi
}

do_install () {
    cat pcbasic/info/VERSION
    echo "INSTALLATION SCRIPT"
    echo 

    #default installation directory
    DEFAULT_DIR="/opt/pcbasic/"
    DESKTOP_DIR="/usr/share/applications"
    ICON_DIR="/usr/share/icons"

    if [ "$(id -u)" != "0" ]; then
        echo -n "NOTE: You are running this script without root privileges, "
        echo "which means you can install PC-BASIC for your user only."
        echo "If you wish to install to a system-wide directory, run this script with root privileges using sudo $0" 1>&2
        echo
        
        DEFAULT_DIR="$HOME/pcbasic"
        
        # user's runtime data
        DATA_BASE_DIR=$XDG_DATA_HOME
        if [ -z "$DATA_BASE_DIR" ]; then
            DATA_BASE_DIR="$HOME/.local/share"
        fi
        DATA_DIR="$DATA_BASE_DIR/pcbasic"

        # user's config
        SETTINGS_DIR=$XDG_CONFIG_HOME
        if [ -z "$SETTINGS_DIR" ]; then
            SETTINGS_DIR="$HOME/.config"
        fi
        SETTINGS_DIR="$SETTINGS_DIR/pcbasic"

        DESKTOP_DIR="$DATA_BASE_DIR/applications"
        ICON_DIR="$DATA_BASE_DIR/icons"
    fi

    echo -n "In what directory would you like to install PC-BASIC (default: $DEFAULT_DIR) ? "
    read INSTALL_DIR

    if [ -z "$INSTALL_DIR" ]; then
        INSTALL_DIR="$DEFAULT_DIR"
    fi

    check_permissions

    UNINSTALLER="$INSTALL_DIR/uninstall.sh"

    echo
    echo "SUMMARY OF WHAT WILL BE DONE:"
    echo "I will install PC-BASIC to directory $INSTALL_DIR"
    if [ "$(id -u)" = "0" ]; then
        echo "I will create a symbolic link /usr/bin/pcbasic"
    else
        echo "Your user settings will be stored in $SETTINGS_DIR"
        echo "Runtime data will be stored in $DATA_DIR"
    fi

    echo "I will create a desktop menu entry $DESKTOP_DIR/pcbasic.desktop"
    echo "I will create an icon $ICON_DIR/pcbasic.png"
    echo "I will create an uninstall script $UNINSTALLER"

    echo
    echo -n "Start installation [y/N] ? "
    read ANSWER

    if [ "$ANSWER" != "y" -a "$ANSWER" != "Y" ]; then
        abort
    fi


    echo
    echo "Copying program files ... "
    # make list of directories and files for uninstall log
    mkdir -p "$INSTALL_DIR"

    cd pcbasic
    DIRS=$(find ./* -type d -print)
    FILES=$(find ./* -type f -print)
    cd ..
    
    for dir in $DIRS; do
        mkdir -p "$INSTALL_DIR/$dir"
    done

    for file in $FILES; do
        cp "pcbasic/$file" "$INSTALL_DIR/$file"
    done
    
    if [ "$(id -u)" = "0" ]; then
        echo "Creating symlink ... "
        ln -s "$INSTALL_DIR/pcbasic" "/usr/bin/pcbasic"
    fi

    echo "Creating menu entry ... "
    DESKTOP_FILE="$DESKTOP_DIR/pcbasic.desktop"
    echo "[Desktop Entry]" > $DESKTOP_FILE
    echo "Name=PC-BASIC 3.23" >> $DESKTOP_FILE
    echo "GenericName=GW-BASIC compatible interpreter" >> $DESKTOP_FILE
    echo "Exec=$INSTALL_DIR/pcbasic" >> $DESKTOP_FILE
    echo "Terminal=false" >> $DESKTOP_FILE
    echo "Type=Application" >> $DESKTOP_FILE
    echo "Icon=pcbasic.png" >> $DESKTOP_FILE
    echo "Categories=Development;IDE;" >> $DESKTOP_FILE

    echo "Creating icon ... "
    cp pcbasic.png "$ICON_DIR/pcbasic.png"

    echo "Creating uninstaller ... "
    echo "#!/bin/sh" > $UNINSTALLER
    echo "DESKTOP_DIR=$DESKTOP_DIR" >> $UNINSTALLER
    echo "ICON_DIR=$ICON_DIR" >> $UNINSTALLER
    echo "INSTALL_DIR=$INSTALL_DIR">> $UNINSTALLER
    
    # invert dirs to delete them recursively
    INVERTED_DIRS=$(echo "$DIRS" | sed '1!G;h;$!d')
    echo "DIRS='$INVERTED_DIRS'" >> $UNINSTALLER
    echo "FILES='$FILES'" >> $UNINSTALLER
    cat $SCRIPT >> $UNINSTALLER
    chmod ugo+x $UNINSTALLER

    echo
    echo "INSTALLATION COMPLETED."
    do_close
}

do_uninstall () {
    echo "UNINSTALL PC-BASIC"
    echo
    
    check_permissions
    
    echo "SUMMARY OF WHAT WILL BE DONE:"
    echo "I will delete the icon $ICON_DIR/pcbasic.png"
    echo "I will delete the desktop menu entry $DESKTOP_DIR/pcbasic.desktop"
    if [ "$(id -u)" = "0" ]; then
        echo "I will delete the symlink /usr/bin/pcbasic"
    fi
    echo "I will delete program files from $INSTALL_DIR"
    echo
    
    echo -n "Start un-installation [y/N] ?"
    read ANSWER
    if [ "$ANSWER" != "y" -a "$ANSWER" != "Y" ]; then
        abort
    fi
    echo 
    
    echo "Removing icon ... "
    rm "$ICON_DIR/pcbasic.png"
    
    echo "Removing menu entry ... "
    rm "$DESKTOP_DIR/pcbasic.desktop"
    
    if [ "$(id -u)" = "0" ]; then
        echo "Removing symlink ... "
        rm /usr/bin/pcbasic
    fi
    
    echo "Removing program files ... "
#    if [ -n "$INSTALL_DIR" ]; then
#        rm -r "$INSTALL_DIR"
#    fi
    for file in $FILES; do
        rm "$INSTALL_DIR/$file"
    done
    for dir in $DIRS; do
        rmdir "$INSTALL_DIR/$dir"
    done
    rm "$INSTALL_DIR/uninstall.sh"
    rmdir "$INSTALL_DIR"

    echo 
    echo "UNINSTALL COMPLETED"
}


if [ ! -t 1 ]; then 
    if [ "$SPAWNED" = "spawned"  -o  -z $DISPLAY  ]; then
	    >&2 echo "This script must be run interactively."
        exit 1
    else
	    xterm -e $0 spawned &
	    exit
    fi  
fi

if [ $(basename $SCRIPT) = "uninstall.sh" ]; then
    do_uninstall
else
    do_install
fi

