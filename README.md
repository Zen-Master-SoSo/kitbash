# KitBash

A GUI application which you can use to create a new SFZ drumkit from pieces of other drumkits.

## Intro

Got a drumkit [SFZ](https://sfzformat.com/) that sounds pretty good, but
there's just one instrument that doesn't quite cut it? Want to replace that one
snare, or even that whole set of tom-toms?

That's what kitbash was written for!

Kitbash allows you to create projects in which you can import mutiple drumkits
from SFZ files, select the pieces of each kit you want, then export the
finished drumkit to a new SFZ.

## Usage

Starting with an empty project, use the "Edit" -> "Load Drumkit" menu, or click
on the "plus" symbol in the toolbar. You'll see all the instruments defined in
the drumkit you just loaded, grouped into categories, such as "Snares", "Tom
toms", "Hi-hats", etc.

### Audio preview

To listen to audio playback, you need to select an "Audio sink" from the dropdown
list at the top-right of the window. You audio out devices should be listed
there. Note that this is a JACK application, and your JACK audio connection kit
server must be running to play audio.

To preview the sound of each instrument, click on the instrument name.
Releasing the mouse stops the playback.

To preview the drumkit you are assembling, you need to send it MIDI note
events. Choose the MIDI source from the dropdown list at the top-right area of
the window, and send MIDI events. A MIDI source can be an external device, like
a MIDI keyboard, or the MIDI output of another program, such as
[qtractor](https://qtractor.org/), [MuseScore](https://musescore.com/), or
[JackMIDILooper](https://github.com/Zen-Master-SoSo/jack_midi_looper).

### Instrument selection

The instruments selected to be included in your final drumkit are indicated by
the check boxes next to the instrument and category names.

Check the box next to a category to select all the instruments in that category
for inclusion in your new drumkit. Check the checkbox next to any individual
instrument (i.e. "Ride Bell"), to include only that instrument.

When you load the first drumkit, all categories and instruments are selected.
Load another drumkit in the same way as you did the first (using the menu or
the toolbar). Selecting an instrument from one drumkit de-selects that
instrument from all other loaded drumkits.

You can make changes while playing a loop from the incoming MIDI source, and
the changes are (almost) immediately made to the "bashed" drumkit you are
making.

### Exporting SFZ

When you're satisfied with what you've selected, you can save the "bashed"
drumkit as an .sfz file in a new location. From the menu, select "File" ->
"Save Bashed Kit As..." and choose the location. Or, click the corresponding
icon in the toolbar.


### Saving a project

A "project" is a list of the source SFZs and which groups and instruments from
each them are selected. You can save a project for later, make whatever changes
you desire, and then export the SFZ you created again. This way, you don't have
to start from scratch every time you wish to make that one small change.


## Install

Install in the usual way:

```bash
$ pip install kitbash
```

### Requirements

You'll need both [JACK audio connection kit](https://jackaudio.org/) and
[liquidsfz](https://github.com/swesterfeld/liquidsfz) in order to have live
previews. You can run the program without either, but you won't be able to
listen to your changes as you are making them.

To install JACK:

```bash
$ sudo apt install jackd
```

...or...

```bash
$ sudo dnf install jackd
```

To install liquidsfz:

```bash
$ git clone https://github.com/swesterfeld/liquidsfz.git
```

... and follow the instructions found in the liquidsfz README to install it.



