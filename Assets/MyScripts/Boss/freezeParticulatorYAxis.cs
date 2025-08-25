using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class freezeParticulatorYAxis : MonoBehaviour
{
	private float original_y_value;
    // Start is called before the first frame update
    void Start()
    {
        original_y_value = transform.position.y;
    }

    // Update is called once per frame
    void Update()
    {
        transform.position = new Vector2(transform.position.x, original_y_value);
    }
}
