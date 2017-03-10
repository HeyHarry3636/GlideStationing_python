##---------------------------------------------------------------------------------------------------------------------------
##  Script Name: Glide Structure Stationing [StructureStationing.py]
##
##  Given 3-dimensional survey data, this script transforms the 3-d data into 2-dimensional (x,z) data so that the
##  cross-sectional areas of design structures can be compared to regional curves and/or design dimensions.
##
##  Author: Michael harris
##  Date: 09/01/16
##---------------------------------------------------------------------------------------------------------------------------

#Import Modules
import arcpy, pyodbc, shutil, os, time

#Set environments
arcpy.env.overwriteOutput = True
arcpy.env.XYResolution = "0.00001 Meters"
arcpy.env.XYTolerance = "0.0001 Meters"

####Input data types
##wrkSpace = Workspace
##glidePoints = Feature Layer
##glideNameField = Field (obtained from glidePoints)
##structurePts = Feature Class [output]
##rmpLoc = Workspace/FileName

#Set user-defined inputs
wrkSpace = arcpy.GetParameterAsText(0)
glidePoints = arcpy.GetParameterAsText(1)
glideNameField = arcpy.GetParameterAsText(2)
rmpLoc = arcpy.GetParameterAsText(3)

###Input Glide Points differentiated by name (Glide1, Glide2, etc...)
##wrkSpace = r"D:\Users\miharris\Desktop\pyScriptTest"
##glidePoints = r"D:\Users\miharris\Desktop\pyScriptTest\glidesScript.shp"
##glideNameField = "Crossing" #User input defining the field that the glides are named after
####structurePts = r"D:\Users\miharris\Desktop\pyScriptTest\GISfiles\structureStationing.shp"
##rmpLoc = r"D:\Users\miharris\Desktop\tempLoc\rmp_DB.mdb"

#Save variables in memory
glideBox = "in_memory\\glideBox"
glideLines = "in_memory\\glideLines"
glideLinesSplit = "in_memory\\glideLinesSplit"
shortLinePointLayer = "in_memory\\shortLinePointLayer"
shortLinePoint = "in_memory\\shortLinePoint"
glideMidLine = "in_memory\\glideMidLine"
glideMidLineJoin = "in_memory\\glideMidLineJoin"
glideMidLineRoute = "in_memory\\glideMidLineRoute"
glideMidLineRouteJoin = "in_memory\\glideMidLineRouteJoin"
glideMidLineRouteFC = "in_memory\\glideMidLineRouteFC"

#Set datum/coordinate system same as input glide points
spatial_reference = arcpy.Describe(glidePoints).spatialReference

try:
    #Create folder for GIS export files
    gisPath = wrkSpace + r"\GISfiles"
    if not os.path.exists(gisPath):
        os.makedirs(gisPath)

    #Set arcpy workspace
    arcpy.env.workspace = gisPath

    #Create the outer boundary or box that will set the stationing
    arcpy.MinimumBoundingGeometry_management(glidePoints, glideBox, "RECTANGLE_BY_WIDTH", "LIST", glideNameField, "MBG_FIELDS")

    #Create line that is halfway between the length of the box, this will be what the stationing is based off of
    #Create lines from glideBox polygon, creates ONE line for each polygon (I need four separate lines)
    arcpy.FeatureToLine_management(glideBox, glideLines)

    #Divide the lines based on the vertices (preserve the points), this will create FOUR separate lines
    arcpy.SplitLine_management(glideLines, glideLinesSplit)

    #Add field to glideLinesSplit to compute the length of each line, and the identifier for the shortest lines
    arcpy.AddField_management(glideLinesSplit, "lineLngth", "DOUBLE", 15, 3)
    arcpy.AddField_management(glideLinesSplit, "shrtLineID", "SHORT")

    #function to determine if values of the MBG_width(from min bounding geometry) are equal to the actual length of the polylines
    def nearlyEqual(a, b, sigFig):
        return ( a==b or int(a*10**sigFig) == int(b*10**sigFig) )

    #Compute the length of the lines in glideLinesSplit
    updateRows = arcpy.da.UpdateCursor(glideLinesSplit, ["SHAPE@", "MBG_WIDTH", "MBG_Length", "lineLngth", "shrtLineID"])
    for row in updateRows:
        row[3] = row[0].getLength("PLANAR", "METERS")
        if nearlyEqual(row[1], row[3], 2) == True:
            row[4] = 1 #1 = short line
        else:
            row[4] = 0 #0 = long line
        updateRows.updateRow(row)
    del updateRows
    del row

    #Create new feature class from the short line segments
    #I had to change the shrtLineID field from a 'TEXT' to a 'SHORT', SQL expression didn't want to work with "short" and "long" as id's, used 1's and 0's instead
    shortExpr = "shrtLineID = 1"
    glideLinesShort = arcpy.FeatureClassToFeatureClass_conversion(glideLinesSplit, gisPath, "glideLinesShort", shortExpr)

    #Add X_mid and Y_mid fields to glideLinesShort, so we can find the middle of each short line
    fieldNames = ["X_mid", "Y_mid"]
    for fld in fieldNames:
        arcpy.AddField_management(glideLinesShort, fld, "DOUBLE")

    #Use position along line geometry to assign X/Y mid values
    updateRows = arcpy.da.UpdateCursor(glideLinesShort, ["SHAPE@", "X_mid", "Y_mid"])
    for row in updateRows:
        row[1] = row[0].positionAlongLine(0.50, True).firstPoint.X
        row[2] = row[0].positionAlongLine(0.50, True).firstPoint.Y
        updateRows.updateRow(row)
    del updateRows
    del row

    #Create XY points using X_mid and Y_mid fields
    arcpy.MakeXYEventLayer_management(glideLinesShort, "X_mid", "Y_mid", shortLinePointLayer, spatial_reference)

    #Convert in memory layer into a feature class
    arcpy.FeatureToPoint_management(shortLinePointLayer, shortLinePoint)

    #Create line that connects the points, unique field will be the crossing ID
    arcpy.PointsToLine_management(shortLinePoint, glideMidLine, glideNameField)

    #Join glideMidLine and glideMidPoint so that the lines have all of the attributes that the points do
    glideMidLineJoin = arcpy.JoinField_management(glideMidLine, glideNameField, shortLinePoint, glideNameField)

    #Copy joined features into new feature class
    glideMidLineFC = arcpy.CopyFeatures_management(glideMidLineJoin, gisPath + "\\" + "glideMidLineFC")

    #Create a route enabled line using glideMidLineFC
    #Add fields for route
    fieldNames = ["Start", "End"]
    for fld in fieldNames:
        arcpy.AddField_management(glideMidLineFC, fld, "DOUBLE")
    arcpy.AddField_management(glideMidLineFC, "Route", "TEXT")

    #Calculate fields
    updateRows = arcpy.da.UpdateCursor(glideMidLineFC, ["SHAPE@", "Start", "End", "Route", "FID"])
    for row in updateRows:
        row[1] = 0
        row[2] = row[0].getLength("PLANAR", "FEET")
        row[3] = row[4]
        updateRows.updateRow(row)
    del updateRows
    del row

    #Create routes using linear referencing toolbox
    arcpy.CreateRoutes_lr(glideMidLineFC, "Route", glideMidLineRoute, "TWO_FIELDS", "Start", "End")

    #Join glideMidLineRoute and glideMidLineFC so that the lines have all of the attributes that the points do
    glideMidLineRouteJoin = arcpy.JoinField_management(glideMidLineRoute, "Route", glideMidLineFC, "Route")

    #Copy joined features into new feature class/then delete join to remove lock on data
    arcpy.CopyFeatures_management(glideMidLineRouteJoin, glideMidLineRouteFC)

    #Use Locate Points along route to find the stationing for the structure(glide) points
    props = "RID POINT MEAS"
    outputStationTable = arcpy.LocateFeaturesAlongRoutes_lr(glidePoints, glideMidLineRouteFC, "Route", 10, gisPath + "\\" + "outputStationTable", props, "FIRST", "DISTANCE", "NO_ZERO", "FIELDS", "NO_M_DIRECTION")

    #Convert table to a layer
    outputStationTableLayer = arcpy.MakeXYEventLayer_management(outputStationTable, "Field3", "Field2", "outputStationTableLayer", spatial_reference, "Field4")

    #Create personal geodatabase (.mdb) so that the data is queryable using PYODBC module
    dbName = "exportDB.mdb"
    arcpy.CreatePersonalGDB_management(gisPath, dbName)
    exportLoc = gisPath + "\\" + dbName

    #Convert the layer into a feature class
    structureStationing = arcpy.FeatureToPoint_management(outputStationTableLayer, gisPath + "\structureStationing.shp")

    #Export the completed structure stationing shapefile to the empty personal geodatabase
    arcpy.FeatureClassToGeodatabase_conversion(structureStationing, exportLoc)

    #Delete objects
    arcpy.Delete_management("in_memory\\glideBox")
    arcpy.Delete_management("in_memory\\glideLines")
    arcpy.Delete_management("in_memory\\glideLinesSplit")
    arcpy.Delete_management(gisPath + "\\" + "glideLinesShort.shp")
    arcpy.Delete_management("in_memory\\shortLinePointLayer")
    arcpy.Delete_management("in_memory\\shortLinePoint")
    arcpy.Delete_management("in_memory\\glideMidLine")
    arcpy.Delete_management(gisPath + "\\" + "glideMidLineFC.shp")
    arcpy.Delete_management("in_memory\\glideMidLineJoin")
    arcpy.Delete_management("in_memory\\glideMidLineRoute")
    arcpy.Delete_management("in_memory\\glideMidLineRouteJoin")
    arcpy.Delete_management("in_memory\\glideMidLineRouteFC")
    arcpy.Delete_management(gisPath + "\\" + "outputStationTable")
    arcpy.Delete_management(gisPath + "\\" + "outputStationTableLayer")

    #############################################################################################################################
    #############################################################################################################################

    #Use PYODBC module to manipulate and query data and to create the RMX file
    #Set the connection string to the microsoft access database and the location of the access database
    cnxnString = r'DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ='

    #Use the connect method to link the python script to the database
    cnxn = pyodbc.connect(cnxnString + rmpLoc)

    #Do your work in the cursor
    crsr = cnxn.cursor()

    #Using a blank rvrmrph file as a template
    #Select full table from exportLoc and copy to rmpLoc (this SQL copies over all
    SQL0 = "SELECT * INTO tbStructure FROM structureStationing IN '{0}';".format(exportLoc)
    crsr.execute(SQL0)

    #Updates the 'river' value and river name for the glide structure cross-sections
    SQLA = "UPDATE tbRiver SET fdRiverName='RiverStructure' WHERE fdRiverID=1;"
    crsr.execute(SQLA)

    #Updates the 'reach' value and reach name for the glide structure cross-sections
    SQLB = "UPDATE tbReach SET fdReachName='Structure Stationing' WHERE fdRiverID=1;"
    crsr.execute(SQLB)

    #Find all unique cross-section names from the tbStructure table using the RID and crossing columns
    SQLC = 'SELECT DISTINCT RID, CROSSING FROM tbStructure'
    glideList = []
    for row in crsr.execute(SQLC):
        rowID = str(row.RID)
        rowCRS = str(row.CROSSING)
        glideList.append((rowID, rowCRS))

    #Insert all unique values into the tbCrossSection table
    xsIdList = []
    for values in glideList:
        xsIdList.append(values[0])
        SQLD = "INSERT INTO tbCrossSection (fdCrossSectionID, fdCrossSectionName, fdReachID) VALUES ('{0}', '{1}', '{2}');".format(values[0], values[1], 1)
        crsr.execute(SQLD)

    #In the tbCSFieldData table, add the elevation (fdElevation) and horizontal distance (fdHorDist) from the ArcMap export using the XSid (fdCrossSectionID)
    SQLE = 'SELECT RID, MEAS, FIELD4, FIELD5 FROM tbStructure'
    objListIni = []

    #Create a sort order based on the unique cross-section ID
    for row in crsr.execute(SQLE):
        objListIni.append((row.RID, row.MEAS, row.FIELD4, str(row.FIELD5)))

    #Sort the list by the glideStructureID then by the sortOrderID
    objListIni.sort(key=lambda item: (item[0], item[1]), reverse=False)

    #Create a sort order based on the unique cross-section ID from the sorted list
    sortOrderID = 0
    prevRowID = 0
    objList = []
    for row in objListIni:
        currentRowID = row[0]
        if currentRowID == prevRowID:
            sortOrderID = sortOrderID + 1
        else:
            sortOrderID = 1
        newTuple = (sortOrderID,)
        objList.append((row + newTuple))
        prevRowID = row[0]

    #Add glide structure data to the CSFieldData table
    for vals in objList:
        SQLF = "INSERT INTO tbCSFieldData (fdCrossSectionID, fdHorDist, fdElevation, fdNote, fdSortOrder) VALUES ('{0}', '{1}', '{2}', '{3}', '{4}');".format(vals[0], vals[1], vals[2], vals[3], vals[4])
        crsr.execute(SQLF)

    #Delete tbStructure table that was added at the beginning of the script
    SQLG = 'DROP TABLE tbStructure'
    crsr.execute(SQLG)

    #You must commit your changes for them to save
    #THIS NEEDS TO HAPPEN BEFORE I TRY WRITING
    cnxn.commit()

    #Delete all records from tables so that the original file can be used again
    SQLH = 'DELETE * FROM tbCrossSection'
    SQLI = 'DELETE * FROM tbCSFieldData'
    crsr.execute(SQLH)
    crsr.execute(SQLI)

    #You must commit your changes for them to save
    cnxn.commit()
    #Close the database connection
    cnxn.close()

    #Delete exported personal geodatabase/.mdb as it is no longer used
    arcpy.Delete_management(exportLoc)

    arcpy.AddMessage("The script has completed successfully")
    print "Script has completed successfully"


except arcpy.ExecuteError:
    print "went exception loop"
    msgs = arcpy.GetMessages(2)
    arcpy.AddError(msgs)

except:
    print "went exception loop"
    import sys, traceback
    tb = sys.exc_info()[2]
    tbinfo = traceback.format_tb(tb)[0]
    pymsg = 'PYTHON ERRORS:\nTraceback info:\n{0}\nError Info:\n{1}'\
          .format(tbinfo, str(sys.exc_info()[1]))
    msgs = 'ArcPy ERRORS:\n {0}\n'.format(arcpy.GetMessages(2))
    arcpy.AddError(pymsg)
    arcpy.AddError(msgs)




