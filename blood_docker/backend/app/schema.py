from pydantic import BaseModel
from typing import Optional


class BloodTestInput(BaseModel):
    creatinine_0h:  Optional[float] = None
    glucose_0h:     Optional[float] = None
    hemoglobin_0h:  Optional[float] = None
    lactate_0h:     Optional[float] = None
    platelet_0h:    Optional[float] = None
    potassium_0h:   Optional[float] = None
    sodium_0h:      Optional[float] = None
    wbc_0h:         Optional[float] = None
    troponin_t_0h:  Optional[float] = None
    bnp_0h:         Optional[float] = None

    class Config:
        json_schema_extra = {
            "example": {
                "creatinine_0h":  2.1,
                "glucose_0h":     180.0,
                "hemoglobin_0h":  8.5,
                "lactate_0h":     3.8,
                "platelet_0h":    95.0,
                "potassium_0h":   5.2,
                "sodium_0h":      132.0,
                "wbc_0h":         14.3,
                "troponin_t_0h":  0.08,
                "bnp_0h":         None
            }
        }


class PredictionResult(BaseModel):
    hemoglobin_down:  float
    creatinine_up:    float
    potassium_worse:  float
    lactate_up:       float
    troponin_up:      float
    warnings:         list[str]
    troponin_note:    Optional[str] = None
