import sys

from pyrevit.framework import List
from pyrevit import forms
from pyrevit import revit, DB, UI
from pyrevit import script


__doc__ = 'Copies selected or current sheet(s) to all ' \
          'projects currently open in Revit. Make sure the destination ' \
          'documents have at least one Legend view. (Revit API does not ' \
          'provide a method to create Legend views so this script needs ' \
          'to duplicate an existing one to create a new Legend.'


logger = script.get_logger()
output = script.get_output()

selection = revit.get_selection()


class Option:
    def __init__(self, op_name, default_state=False):
        self.state = default_state
        self.name = op_name

    def __nonzero__(self):
        return self.state


class OptionSet:
    def __init__(self):
        self.op_copy_vports = Option('Copy Viewports', True)
        self.op_copy_schedules = Option('Copy Schedules', True)
        self.op_copy_titleblock = Option('Copy Sheet Titleblock', True)
        self.op_update_exist_view_contents = \
            Option('Update Existing View Contents')
        # self.op_update_exist_vport_locations = \
        #    Option('Update Existing Viewport Locations')


class CopyUseDestination(DB.IDuplicateTypeNamesHandler):
    def OnDuplicateTypeNamesFound(self, args):
        return DB.DuplicateTypeAction.UseDestinationTypes


class DestDoc:
    def __init__(self, doc):
        self.state = False
        self.dest_doc = doc
        self.name = self.dest_doc.Title

    def __nonzero__(self):
        return self.state


class SheetToCopy:
    def __init__(self, sheet):
        self.state = False
        self.sheet = sheet
        self.name = '{} - {}'.format(sheet.SheetNumber, sheet.Name)
        self.number = sheet.SheetNumber

    def __nonzero__(self):
        return self.state


def error_and_close(msg):
    UI.TaskDialog.Show('pyrevit', msg)
    sys.exit(0)


def get_user_options():
    op_set = OptionSet()
    return_options = \
        forms.SelectFromCheckBoxes.show(
            [getattr(op_set, x) for x in dir(op_set) if x.startswith('op_')],
            title='Select Copy Options',
            button_name='Copy Now')

    if not return_options:
        sys.exit(0)

    return op_set


def get_dest_docs():
    # find open documents other than the active doc
    open_docs = [d for d in revit.docs if not d.IsLinked]
    open_docs.remove(revit.doc)

    if len(open_docs) < 1:
        error_and_close('Only one active document is found. '
                        'At least two documents must be open. '
                        'Operation cancelled.')

    return_options = \
        forms.SelectFromCheckBoxes.show([DestDoc(x) for x in open_docs],
                                        title='Select Destination Documents',
                                        button_name='OK')

    if return_options:
        return [x.dest_doc for x in return_options if x]
    else:
        sys.exit(0)


def get_source_sheets():
    all_sheets = DB.FilteredElementCollector(revit.doc) \
                   .OfClass(DB.ViewSheet) \
                   .WhereElementIsNotElementType() \
                   .ToElements()

    return_options = \
        forms.SelectFromCheckBoxes.show(
            sorted([SheetToCopy(x) for x in all_sheets],
                   key=lambda x: x.number),
            title='Select Sheets to be Copied',
            width=500,
            button_name='Copy Sheets')

    if return_options:
        return [x.sheet for x in return_options if x]
    else:
        sys.exit(0)


def get_default_type(source_doc, type_group):
    return source_doc.GetDefaultElementTypeId(type_group)


def find_first_legend(dest_doc):
    for v in DB.FilteredElementCollector(dest_doc).OfClass(DB.View):
        if v.ViewType == DB.ViewType.Legend:
            return v
    return None


def find_matching_view(dest_doc, source_view):
    for v in DB.FilteredElementCollector(dest_doc).OfClass(DB.View):
        if v.ViewType == source_view.ViewType \
                and v.ViewName == source_view.ViewName:
            if source_view.ViewType == DB.ViewType.DrawingSheet:
                if v.SheetNumber == source_view.SheetNumber:
                    return v
            else:
                return v


def get_view_contents(dest_doc, source_view):
    view_elements = DB.FilteredElementCollector(dest_doc, source_view.Id)\
                      .WhereElementIsNotElementType()\
                      .ToElements()

    elements_ids = []
    for element in view_elements:
        if (element.Category and element.Category.Name == 'Title Blocks') \
                and not OPTION_SET.op_copy_titleblock:
            continue
        elif isinstance(element, DB.ScheduleSheetInstance) \
                and not OPTION_SET.op_copy_schedules:
            continue
        elif isinstance(element, DB.Viewport) \
                or 'ExtentElem' in element.Name:
            continue
        else:
            elements_ids.append(element.Id)
    return elements_ids


def clear_view_contents(dest_doc, dest_view):
    logger.debug('Removing view contents: {}'.format(dest_view.Name))
    elements_ids = get_view_contents(dest_doc, dest_view)

    with revit.Transaction('Delete View Contents', doc=dest_doc):
        for el_id in elements_ids:
            try:
                dest_doc.Delete(el_id)
            except Exception as err:
                continue

    return True


def copy_view_contents(activedoc, source_view, dest_doc, dest_view,
                       clear_contents=False):
    logger.debug('Copying view contents: {}'.format(source_view.Name))

    elements_ids = get_view_contents(activedoc, source_view)

    if clear_contents:
        if not clear_view_contents(dest_doc, dest_view):
            return False

    cp_options = DB.CopyPasteOptions()
    cp_options.SetDuplicateTypeNamesHandler(CopyUseDestination())

    if elements_ids:
        with revit.Transaction('Copy View Contents', doc=dest_doc):
            DB.ElementTransformUtils.CopyElements(
                source_view,
                List[DB.ElementId](elements_ids),
                dest_view, None, cp_options
                )

    return True


def copy_view(activedoc, source_view, dest_doc):
    matching_view = find_matching_view(dest_doc, source_view)
    if matching_view:
        print('\t\t\tView/Sheet already exists in document.')
        opt = OPTION_SET.op_update_exist_view_contents
        if opt:
            if not copy_view_contents(activedoc,
                                      source_view,
                                      dest_doc,
                                      matching_view,
                                      clear_contents=opt):
                logger.error('Could not copy view contents: {}'
                             .format(source_view.Name))

        return matching_view

    logger.debug('Copying view: {}'.format(source_view.Name))
    new_view = None

    if source_view.ViewType == DB.ViewType.DrawingSheet:
        try:
            logger.debug('Source view is a sheet. '
                         'Creating destination sheet.')

            with revit.Transaction('Create Sheet', doc=dest_doc):
                new_view = DB.ViewSheet.Create(dest_doc,
                                               DB.ElementId.InvalidElementId)
                new_view.ViewName = source_view.ViewName
                new_view.SheetNumber = source_view.SheetNumber
        except Exception as sheet_err:
            logger.error('Error creating sheet. | {}'.format(sheet_err))
    elif source_view.ViewType == DB.ViewType.DraftingView:
        try:
            logger.debug('Source view is a drafting. '
                         'Creating destination drafting view.')

            with revit.Transaction('Create Drafting View', doc=dest_doc):
                new_view = DB.ViewDrafting.Create(
                    dest_doc,
                    get_default_type(dest_doc,
                                     DB.ElementTypeGroup.ViewTypeDrafting)
                )
                new_view.ViewName = source_view.ViewName
                new_view.Scale = source_view.Scale
        except Exception as sheet_err:
            logger.error('Error creating drafting view. | {}'
                         .format(sheet_err))
    elif source_view.ViewType == DB.ViewType.Legend:
        try:
            logger.debug('Source view is a legend. '
                         'Creating destination legend view.')

            first_legend = find_first_legend(dest_doc)
            if first_legend:
                with revit.Transaction('Create Legend View', doc=dest_doc):
                    new_view = \
                        dest_doc.GetElement(
                            first_legend.Duplicate(
                                DB.ViewDuplicateOption.Duplicate
                                )
                            )
                    new_view.ViewName = source_view.ViewName
                    new_view.Scale = source_view.Scale
            else:
                logger.error('Destination document must have at least one '
                             'Legend view. Skipping legend.')
        except Exception as sheet_err:
            logger.error('Error creating drafting view. | {}'
                         .format(sheet_err))

    if new_view:
        copy_view_contents(activedoc, source_view, dest_doc, new_view)

    return new_view


def copy_sheet_view(*args):
    return copy_view(*args)


def copy_sheet_viewports(activedoc, source_sheet, dest_doc, dest_sheet):
    existing_views = [dest_doc.GetElement(x).ViewId
                      for x in dest_sheet.GetAllViewports()]

    for vport_id in source_sheet.GetAllViewports():
        vport = activedoc.GetElement(vport_id)
        vport_view = activedoc.GetElement(vport.ViewId)

        print('\t\tCopying/updating view: {}'.format(vport_view.ViewName))
        new_view = copy_view(activedoc, vport_view, dest_doc)

        if new_view:
            if new_view.Id not in existing_views:
                print('\t\t\tPlacing copied view on sheet.')
                with revit.Transaction('Place View on Sheet', doc=dest_doc):
                    DB.Viewport.Create(dest_doc,
                                       dest_sheet.Id,
                                       new_view.Id,
                                       vport.GetBoxCenter())
            else:
                print('\t\t\tView already exists on the sheet.')


def copy_sheet(activedoc, source_sheet, dest_doc):
    logger.debug('Copying sheet {} to document {}'
                 .format(source_sheet.Name,
                         dest_doc.Title))
    print('\tCopying/updating Sheet: {}'.format(source_sheet.Name))
    with revit.TransactionGroup('Import Sheet', doc=dest_doc):
        logger.debug('Creating destination sheet...')
        new_sheet = copy_sheet_view(activedoc, source_sheet, dest_doc)

        if new_sheet:
            if OPTION_SET.op_copy_vports:
                logger.debug('Copying sheet viewports...')
                copy_sheet_viewports(activedoc, source_sheet,
                                     dest_doc, new_sheet)
            else:
                print('Skipping viewports...')
        else:
            logger.error('Failed copying sheet: {}'.format(source_sheet.Name))


dest_docs = get_dest_docs()
doc_count = len(dest_docs)

source_sheets = get_source_sheets()
sheet_count = len(source_sheets)

OPTION_SET = get_user_options()

total_work = doc_count * sheet_count
work_counter = 0

for dest_doc in dest_docs:
    output.print_md('**Copying Sheet(s) to Document:** {0}'
                    .format(dest_doc.Title))

    for source_sheet in source_sheets:
        print('Copying Sheet: {0} - {1}'.format(source_sheet.SheetNumber,
                                                source_sheet.Name))
        copy_sheet(revit.doc, source_sheet, dest_doc)
        work_counter += 1
        output.update_progress(work_counter, total_work)

    output.print_md('**Copied {} sheets to {} documents.**'
                    .format(sheet_count, doc_count))