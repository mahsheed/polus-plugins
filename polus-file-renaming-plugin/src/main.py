import argparse
import logging
from pathlib import Path
import regex as re
import shutil

def convert_filename(input_image, fpattern, outpattern):
    """This function performs bulk of filename conversion.
    
    This function takes the input args to produce the desired filepath. 
    If the user inputs a regex pattern that is a character and expects 
    a digit, it marks the file pattern to be processed by a different 
    function.
    
    Args:
        input_image: img_x01_y01_GFP.tif
        fpattern: img_x{row:dd}_y{col:dd}_{channel:c+}.tif
        outpattern: new_x{row:dd}_y{col:ddd}_c{channel:ddd}.tif

    Returns:
        temp_fp: new_x01_y001_c_rgxstart_[0-9]{3}_rgxmid_GFP_rgxend_.tif
        """
    #: Separate input and output file pattern components into a list
    fpattern_list = [
        ", ".join(x.split()) for x in re.split(r"[{}]", fpattern) if x.strip()
        ] 
    #: ["n", "{row:d}", "_y", "{col:dd}", "_c", "{chan:ddd}", ".tif"] 
    outpattern_list = [
        ", ".join(x.split()) for x in re.split(r"[{}]", outpattern) if x.strip()
        ]    
    #: Convert file pattern to computer-readable regex and store in dict
    pseudoregex_trueregex_in_dict = translate_regex(fpattern_list) 
    pseudoregex_trueregex_out_dict = translate_regex(outpattern_list)
    #: Build match groups column 
    logger.info("Psy in vals: {}".format(pseudoregex_trueregex_in_dict))
    #: Add parentheses to match groups lacking parentheses
    match_grouping_list = [
        "(" + item + ")" if item.startswith("(") == False else item 
        for item in pseudoregex_trueregex_in_dict
        ]
    regex_groups = "".join(match_grouping_list)
    logger.debug("Regex Groups: {}".format(regex_groups))
    logger.debug("Image Name: {}".format(input_image))
    #: Search filename for regex match groups
    matches = re.search(regex_groups, input_image)
    logger.debug("Matches: {}".format(matches))
    #: Create intermediate output filename with markers for c-->d regex 
    #: Ex: new_x01_y001_c_rgxstart_[0-9]{3}_rgxmid_GFP_rgxend_.tif
    input_loc = 0
    output_loc = 0
    for part in range(0,len(pseudoregex_trueregex_in_dict)):
        # We only change the ones that are not regex here
        #: Process non-regex matches (lack [0-9] or [a-zA-Z])
        if "[" not in pseudoregex_trueregex_in_dict[part]:
            match_in_input = pseudoregex_trueregex_in_dict[part]
            match_in_output = pseudoregex_trueregex_out_dict[part]
            #: returns the index of first occurrence of the substring
            loc = input_image.find(match_in_input, input_loc)
            temp_fp = (
                input_image[0: loc] 
                + match_in_output 
                + input_image[loc + len(match_in_input):]
                )
            #: Starting input_loc is where we are searching from
            input_loc = loc + len(match_in_output)
            output_loc = temp_fp.find(match_in_output, output_loc)
            input_image = temp_fp
        else:
            rgx_match_in = pseudoregex_trueregex_in_dict[part]
            rgx_match_out = pseudoregex_trueregex_out_dict[part]
            result = re.search(rgx_match_in, input_image[input_loc:])
            match_in_input = result.group(0)
            match_in_output = format_output_digit(
                match_in_input, rgx_match_in, rgx_match_out
                )
            loc = input_image.find(match_in_input, input_loc)
            temp_fp = (
                input_image[0: loc] 
                + match_in_output 
                + input_image[loc 
                + len(match_in_input):]
                )
            #: Starting input_loc is where we are searching from
            input_loc = loc + len(match_in_output)
            output_loc = temp_fp.find(match_in_output, output_loc)
            input_image = temp_fp
    return temp_fp
  
def format_output_digit(match_in_input, rgx_match_in, rgx_match_out):
    """
    Change number of digits based on regex pattern or mark if c->d.
    
    This function formats the number of digits using the # of digits in
    the output format. This marks any substring where the input 
    pattern is a character and the output pattern is a digit for later 
    processing. Otherwise, where input and output pattern data types 
    agree, it converts the value to a designated number of output 
    digits/characters.
    
    Example:
    If input starts with [a-z] and output starts with [0-9], one may 
    expect the following:
    
    Args:
        match_in_input: GFP
        rgx_match_in: [a-zA-Z]{2}
        rgx_match_out:[0-9]{3}
        
    Returns:
        formatted_digit: 001
    """
    #: Mark substring where input pattern is char and output is digit
    if rgx_match_in.startswith("[a-zA-Z]") and "[0-9]" in rgx_match_out:
        formatted_digit = (
            "_rgxstart_" 
            + rgx_match_out 
            + "_rgxmid_" 
            + match_in_input 
            + "_rgxend_"
            )
    elif rgx_match_out.endswith("}"):
        loc = rgx_match_out.find("{") + 1
        num = str(rgx_match_out[loc:-1])
        #: d for Decimal Integer. Outputs the number in base 10.
        if rgx_match_out.startswith("[0-9]"):
            format_str = "{:0" + num + "d}"
        #: s for String format.
        elif rgx_match_out.startswith("[a-zA-Z]"):
            format_str = "{:0" + num + "s}"
        formatted_digit = str(format_str.format(int(match_in_input)))
    #: For remaining, no need to fix # of output digits/characters
    else:
        formatted_digit = match_in_input
    return formatted_digit

def translate_regex(fpatt_list):
    """
    Convert user-supplied "pseudoregex" to the proper regex format. 
    
    Store properly formatted regex as a value in a dictionary.
    
    Args:
        fpatt_list: ["img_x", "row:dd", "_y", "col:dd", "_", "channel:c+", ".tif"]
        
    Returns:
        rgx_lst: ["img_x", "[0-9]{2}", "_y", "[0-9]{2}", "_", "[a-zA-Z]*", ".tif"]
    """
    new_pattern = ""
    rgx_lst = []
    #: Loop through each match group
    for i in range (0, len(fpatt_list)):
        #: Isolate x:x values
        if ":" in fpatt_list[i]:
            #: Loop through dictionary of variables and regex
            regex_digit = fpatt_list[i].split(":",1)[1]
            #: Properly format file pattern into regex
            new_val = ""
            #: Inform user to keep it as dd, or ff, cc, or ii
            #: Process floats and integers
            if regex_digit == "d+":
                new_val = "[0-9]*"
            elif regex_digit == "c+":
                new_val = "[a-zA-Z]*"
            elif regex_digit == "i+":
                new_val = "[0-9]*"
            elif regex_digit == "f+":
                new_val = "[+-]?([0-9]*[.])?[0-9]+"
            #: Process remaining not listed above
            elif "d" in regex_digit or "i" in regex_digit:
                # Produce a regex group matching digits with # of chars
                digit_count = "{" + str(len(regex_digit)) + "}"
                new_val = "[0-9]" + digit_count
            elif "c" in regex_digit:
                #: count c's
                c_count = "{" + str(len(regex_digit)) + "}"
                new_val = "[a-zA-Z]" + c_count
            new_pattern = new_pattern + new_val
            rgx_lst.append(new_val)      
        else: 
            new_patt = "(" + fpatt_list[i] + ")"
            rgx_lst.append(fpatt_list[i])
            new_pattern = new_pattern + new_patt
    return rgx_lst

def str_to_num(input_file, chan_data_dict_sorted):
    """
    This function converts strings to numbers based on a file pattern.
    
    This function looks for marker that indicates input pattern was 
    character and output pattern was digit.
    Using sorted dictionary of strings from input, assign numbers 1+ 
    to the strings.
    Convert into proper number of digits based on output regex pattern
    
    Args:
        input_file:  image_collection_1/img_x01_y01_GFP.tif
        chan_data_dict_sorted  {
        "1": {fpath: n1_y01_c_rgxstart_[0-9]{3}_rgxmid_DAPI_rgxend_.tif}, 
        "2": {fpath: n1_y01_c_rgxstart_[0-9]{3}_rgxmid_GFP_rgxend_.tif}, 
        "3": {fpath: n1_y01_c_rgxstart_[0-9]{3}_rgxmid_TXRED_rgxend_.tif}} 
        
    Returns:
        final_filename:  n1_y01_c001.tif
    """
    input_file_name = str(Path(input_file).name)
    for k,v in chan_data_dict_sorted.items():
        current_dict = v
        for k2,v2 in current_dict.items():
            if input_file_name == str(k2.name):
                #: get the substring between two markers 
                start = v2.find("_rgxstart_") + len("_rgxstart_")
                end = v2.find("_rgxmid_")
                #: #: [0-9]{3}
                rgx_match_out = v2[start:end]                
                #: Combine chan_num, rgx_match_out, and match_in_input
                chan_num = k
                #: Convert chan_num to correct number of digits
                if rgx_match_out.endswith("}"):
                    loc = rgx_match_out.find("{") + 1
                    num = str(rgx_match_out[loc:-1])
                    format_str = "{:0" + num + "d}"
                    formatted_digit = str(format_str.format(int(chan_num)))
                #: For remaining, no need to fix # of output digits/char
                else:
                    formatted_digit = chan_num
                #: Replace entire string marker with replacement
                start2 = v2.find("_rgxstart_") 
                end2 = v2.find("_rgxend_") + len("_rgxend_")
                final_filename = v2[:start2] + formatted_digit + v2[end2:]
                return final_filename
                
if __name__ == "__main__":
    #: Initialize the logger
    logging.basicConfig(
        format = "%(asctime)s - %(name) - 8s - %(levelname) - 8s - %(message)s",
        datefmt = "%d-%b-%y %H:%M:%S"
        )
    logger = logging.getLogger("main")
    logger.setLevel(logging.DEBUG)
    #: Set up the argument parsing
    logger.info("Parsing arguments...")
    parser = argparse.ArgumentParser(
        prog="main",
        description="""
            Renames files from a given image collection using file 
            renaming pattern. Patterns should be d or i for 
            digit/integer, c for character, f for floating point. 
            Example: dd looks for 2 digits. Add + to prevent fixing the 
            number of output digits/characters."""
        )
    parser.add_argument(
        "--inpDir",
        dest = "inpDir", type=str, 
        help="Input image collection to be processed by this plugin",
        required=True
        )
    parser.add_argument(
        "--outDir", dest="outDir", type=str, 
        help="Output image collection of renamed files",
        required=True
        )
    parser.add_argument(
        "--filePattern", dest="filePattern", type=str, 
        help="Filename pattern used to separate data",
        required=True
        )
    parser.add_argument(
        "--outFilePattern", dest="outFilePattern", type=str, 
        help="Desired filename pattern used to rename and separate data",
        required=True
        )
    #: Parse the arguments
    args = parser.parse_args()
    #: Check for subfolders named images and switch to that subfolder
    inpDir = args.inpDir
    logger.debug("Old input directory: {}".format(inpDir))
    inpDir = Path(inpDir)
    #: outDir is the new csv collection
    outDir = args.outDir
    logger.debug("outDir = {}".format(outDir))
    #: Input pattern is the regex pattern input by user
    filePattern = args.filePattern
    logger.debug("filePattern = {}".format(filePattern))
    #: Output pattern is regex pattern expected by user
    outFilePattern = args.outFilePattern
    logger.debug("output_pattern = {}".format(outFilePattern))
    #: Check that given input directory points to images folder
    logger.info("Navigated to the image collection...")
    #: Define the path:
    logger.debug("Defining paths...")
    input_directory = inpDir
    input_images = [p for p in input_directory.iterdir() if p.is_file()]
    output_files_to_adjust = {}
    for input_file in input_directory.iterdir():
        logger.info("Parsing {}".format(input_file))
        output_file = convert_filename(
            str(input_file.name), filePattern, outFilePattern)
        output_files_to_adjust[input_file] = output_file
        logger.info("Output file location: {}".format(output_file))
    chan_filemarker_dict = {}
    for each_key, each_value in output_files_to_adjust.items():
        #: get the substring between two markers 
        start = each_value.find("_rgxmid_") + len("_rgxmid_")
        end = each_value.find("_rgxend_")
        substring = each_value[start:end]
        chan_filemarker_dict[substring] = {each_key: each_value}
    chan_data_dict = {}  
    for key in sorted(chan_filemarker_dict.keys()):
        chan_data_dict[key] = chan_filemarker_dict[key]
    chan_fmarker_dict = {}
    i = 1
    for k,v in chan_data_dict.items():
        chan_fmarker_dict[i] = v
        i = i + 1
    #: Get output filename/path. Copy to output collection.   
    for input_file in input_directory.iterdir():
        #: final_filename:  newdata_x001_y001_c002.tif
        #:  This function converts marked strings to numbers
        final_fname = outDir / Path(str_to_num(input_file, chan_fmarker_dict))
        shutil.copy2(input_file, final_fname)