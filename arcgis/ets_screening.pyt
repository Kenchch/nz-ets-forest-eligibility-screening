"""ArcGIS Pro toolbox: thin wrapper around the tested ets_screening package."""

import os

import arcpy


class Toolbox:
    def __init__(self):
        self.label = "NZ ETS Forest Land Screening"
        self.alias = "nz_ets_screening"
        self.tools = [ScreenPost1989Candidates]


class ScreenPost1989Candidates:
    def __init__(self):
        self.label = "Screen post-1989 forest-land candidates"
        self.description = (
            "Screening/triage only. This tool does not determine ETS eligibility. "
            "All inputs must use NZTM2000 (EPSG:2193)."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        candidates = arcpy.Parameter(
            displayName="Candidate polygons",
            name="candidates",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Input",
        )
        pre1990 = arcpy.Parameter(
            displayName="Pre-1990 evidence polygons",
            name="pre1990",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Input",
        )
        conservation = arcpy.Parameter(
            displayName="Public conservation polygons",
            name="conservation",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Input",
        )
        # Declared as an input folder on purpose. As direction="Output",
        # ArcGIS raises ERROR 000725 whenever the folder already exists, and
        # this tool is designed to refresh a results folder in place.
        output = arcpy.Parameter(
            displayName="Output folder",
            name="output",
            datatype="DEFolder",
            parameterType="Required",
            direction="Input",
        )
        threshold = arcpy.Parameter(
            displayName="Reject-rate abort threshold",
            name="reject_rate_threshold",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input",
        )
        threshold.value = 0.80
        return [candidates, pre1990, conservation, output, threshold]

    def isLicensed(self):
        return True

    def updateMessages(self, parameters):
        threshold = parameters[4].value
        if threshold is not None and not 0 <= float(threshold) <= 1:
            parameters[4].setErrorMessage("Threshold must be between 0 and 1.")

    def execute(self, parameters, messages):
        from ets_screening.load import read_layer
        from ets_screening.screen import run_screening

        candidate_path, pre1990_path, conservation_path, output_path = [
            parameter.valueAsText for parameter in parameters[:4]
        ]
        threshold = float(parameters[4].value or 0.80)
        arcpy.AddMessage("Loading inputs and asserting EPSG:2193...")
        candidates = read_layer(candidate_path, ("unit_id", "lcdb_class"), "candidates")
        pre1990 = read_layer(pre1990_path, name="pre1990")
        conservation = read_layer(conservation_path, name="conservation")
        manifest = run_screening(candidates, pre1990, conservation, output_path, threshold)
        arcpy.AddMessage(f"Complete: {manifest}")
